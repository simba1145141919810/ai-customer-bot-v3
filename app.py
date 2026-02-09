import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 1. 核心变量 (严格校验) ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 初始化客户端，失败则打印
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")
except Exception as e:
    print(f"CLIENT INIT ERROR: {e}")

MODEL_NAME = "grok-4-1-fast-reasoning"


# --- 2. 强力发送函数 (无论如何都要回一句话) ---
def send_reply(chat_id, text, photo_url=None, buy_url=None):
    reply_markup = None
    if buy_url:
        reply_markup = {"inline_keyboard": [[{"text": "🛒 点击直接购买", "url": buy_url}]]}

    # 尝试发送图片
    if photo_url and photo_url.startswith("http"):
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo_url, "caption": text, "parse_mode": "Markdown",
                   "reply_markup": reply_markup}
        res = requests.post(url, json=payload)
        if res.status_code == 200: return

    # 如果图片发送失败或没有图片，发送纯文字
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": reply_markup}
    requests.post(url, json=payload)


# --- 3. 容错型数据库逻辑 ---
def db_get_order(order_id):
    try:
        # 同时尝试单数和复数，彻底解决表名纠纷
        for table_name in ["orders", "order"]:
            res = supabase.table(table_name).select("*").eq("order_id", str(order_id)).execute()
            if res.data:
                order = res.data[0]
                return f"找到啦！单号 {order_id} 状态：*[{order['status']}]*。物流：{order.get('tracking', '处理中')}。"
        return f"Aiyoh, 数据库里翻遍了也没找到订单 {order_id}。"
    except Exception as e:
        return f"查询时数据库闹脾气了: {str(e)}"


def db_search_product(query):
    try:
        res = supabase.table("products").select("*").ilike("name", f"%{query}%").execute()
        return res.data if res.data else []
    except:
        return []


# --- 4. 稳定的 AI 逻辑 ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    user_text = data["message"].get("text", "")

    # 让 Telegram 显示“正在输入”
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendChatAction",
                  json={"chat_id": chat_id, "action": "typing"})

    try:
        # 极简调用，减少工具调用的判断层级
        tools = [
            {"type": "function", "function": {"name": "get_order",
                                              "parameters": {"type": "object", "properties": {"id": {"type": "string"}},
                                                             "required": ["id"]}}},
            {"type": "function", "function": {"name": "search_item",
                                              "parameters": {"type": "object", "properties": {"q": {"type": "string"}},
                                                             "required": ["q"]}}}
        ]

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个新加坡艺术导购。查询订单请用 get_order，搜东西用 search_item。"},
                {"role": "user", "content": user_text}],
            tools=tools
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                if call.function.name == "get_order":
                    send_reply(chat_id, db_get_order(args.get("id")))
                elif call.function.name == "search_item":
                    items = db_search_product(args.get("q"))
                    if items:
                        item = items[0]
                        send_reply(chat_id, f"*{item['name']}*\n{item['price']}", item.get('img'), item.get('buy_url'))
                    else:
                        send_reply(chat_id, "没找到这款宝贝，看看其他的？")
        else:
            send_reply(chat_id, msg.content)

    except Exception as e:
        send_reply(chat_id, f"AI 思考时断片了: {str(e)}")

    return "ok", 200


@app.route('/')
def home(): return "Ready"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))