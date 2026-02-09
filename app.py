import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 1. 配置加载 (直接从环境读取) ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 初始化客户端 (增加容错)
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")
except Exception as e:
    print(f"Client Init Error: {e}")

MODEL_NAME = "grok-4-1-fast-reasoning"


# --- 2. 增强型发送函数 (带按钮支持) ---
def send_response(chat_id, text, photo_url=None, buy_url=None):
    reply_markup = None
    if buy_url:
        reply_markup = {"inline_keyboard": [[{"text": "🛒 点击直接购买 (Buy Now)", "url": buy_url}]]}

    payload = {
        "chat_id": chat_id,
        "text": text if not photo_url else f"{text}",  # 如果是图片，text会作为caption
        "parse_mode": "Markdown",
        "reply_markup": reply_markup
    }

    try:
        if photo_url and photo_url.startswith("http"):
            url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
            payload["photo"] = photo_url
            payload["caption"] = text
            del payload["text"]
            requests.post(url, json=payload, timeout=10)
        else:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Send Error: {e}")


# --- 3. 数据库查询 (适配 orders 和 products) ---
def db_get_order(order_id):
    try:
        # 这里的表名必须和你的 Supabase 一致
        res = supabase.table("orders").select("*").eq("order_id", str(order_id)).execute()
        if not res.data: return f"Aiyoh, 找不到单号 {order_id}。"
        order = res.data[0]
        return f"找到了！单号 {order_id} 状态：*[{order['status']}]*。物流：{order.get('tracking', '处理中')}。"
    except Exception as e:
        return f"数据库查单出错: {str(e)}"


def db_search_product(query):
    try:
        res = supabase.table("products").select("*").ilike("name", f"%{query}%").execute()
        if not res.data:
            res = supabase.table("products").select("*").ilike("style", f"%{query}%").execute()
        return res.data if res.data else []
    except Exception as e:
        print(f"Product Search Error: {e}")
        return []


# --- 4. 核心 AI 处理层 ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    user_text = data["message"].get("text", "")

    # 1. 立即反馈 Typing 状态
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendChatAction",
                  json={"chat_id": chat_id, "action": "typing"})

    # 2. 调用 AI
    try:
        tools = [
            {"type": "function", "function": {"name": "get_order",
                                              "parameters": {"type": "object", "properties": {"id": {"type": "string"}},
                                                             "required": ["id"]}}},
            {"type": "function", "function": {"name": "search_item",
                                              "parameters": {"type": "object", "properties": {"q": {"type": "string"}},
                                                             "required": ["q"]}}}
        ]

        # 保持极简 Prompt 提高成功率
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个新加坡艺术导购。查询订单用 get_order，搜索产品用 search_item。"},
                {"role": "user", "content": user_text}
            ],
            tools=tools
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                if call.function.name == "get_order":
                    send_response(chat_id, db_get_order(args.get("id")))
                elif call.function.name == "search_item":
                    items = db_search_product(args.get("q"))
                    if items:
                        item = items[0]
                        caption = f"*{item['name']}* - {item['price']}\n_{item.get('desc', '')}_"
                        send_response(chat_id, caption, item.get('img'), item.get('buy_url'))
                    else:
                        send_response(chat_id, "抱歉，没找到这款宝贝。")
        else:
            send_response(chat_id, msg.content)

    except Exception as e:
        send_response(chat_id, f"AI 处理出错: {str(e)}")

    return "ok", 200


@app.route('/')
def home(): return "AI Hub Online"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)