import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 配置初始化 ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")
MODEL_NAME = "grok-4-1-fast-reasoning"


# --- 功能函数：发送消息 ---
def send_response(chat_id, text, photo_url=None, buy_url=None):
    reply_markup = None
    if buy_url:
        reply_markup = {"inline_keyboard": [[{"text": "🛒 点击直接购买 (Buy Now)", "url": buy_url}]]}

    try:
        if photo_url and photo_url.startswith("http"):
            url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
            payload = {"chat_id": chat_id, "photo": photo_url, "caption": text, "parse_mode": "Markdown",
                       "reply_markup": reply_markup}
        else:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": reply_markup}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram API Error: {e}")


# --- 数据库逻辑 (重点加固) ---
def db_get_order(order_id):
    try:
        # 强制将 order_id 转为字符串查询，兼容 text 类型的列
        order_str = str(order_id).strip()
        # 尝试从 orders 表查询
        res = supabase.table("orders").select("*").eq("order_id", order_str).execute()

        if not res.data:
            return f"Aiyoh, 我们的数据库里找不到单号 `{order_str}` 呢。要不你确认一下号码？"

        order = res.data[0]
        # 使用 .get 方式读取，防止列名不存在导致崩溃
        status = order.get("status", "处理中")
        items = order.get("items", "神秘商品")
        tracking = order.get("tracking", "暂无物流信息")

        return f"找到了！订单 `{order_str}` 状态：*[{status}]*\n商品：{items}\n物流：{tracking}"
    except Exception as e:
        # 如果报错，通过机器人把报错内容发出来，方便我们排查
        return f"查询时发生了点小意外: {str(e)}"


def db_search_product(query):
    try:
        res = supabase.table("products").select("*").ilike("name", f"%{query}%").execute()
        if not res.data:
            res = supabase.table("products").select("*").ilike("style", f"%{query}%").execute()
        return res.data if res.data else []
    except Exception as e:
        return []


# --- Webhook 接口 ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    user_text = data["message"].get("text", "")

    # Typing 状态
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendChatAction",
                  json={"chat_id": chat_id, "action": "typing"})

    try:
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
                {"role": "system",
                 "content": "你是一个新加坡艺术导购。查询订单请调用 get_order，搜索产品请调用 search_item。如果用户没给单号，请先询问单号。"},
                {"role": "user", "content": user_text}
            ],
            tools=tools
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                if call.function.name == "get_order":
                    # 调用加固后的查单函数
                    send_response(chat_id, db_get_order(args.get("id")))
                elif call.function.name == "search_item":
                    items = db_search_product(args.get("q"))
                    if items:
                        item = items[0]
                        send_response(chat_id, f"*{item['name']}* - {item['price']}\n_{item.get('desc', '')}_",
                                      item.get('img'), item.get('buy_url'))
                    else:
                        send_response(chat_id, "抱歉，没搜到这款宝贝。")
        else:
            send_response(chat_id, msg.content)

    except Exception as e:
        send_response(chat_id, f"系统思考出错了: {str(e)}")

    return "ok", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))