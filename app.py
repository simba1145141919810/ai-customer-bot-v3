import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 1. 核心安全配置 ---
GROK_KEY = os.environ.get("GROK_API_KEY")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")

client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")
MODEL_NAME = "grok-4-1-fast-reasoning"

# --- 2. 商业级模拟数据库 (建议下一步接入 Supabase) ---
FAKE_DB = {
    "orders": {
        "14514": {"status": "已发货", "items": "极简几何手机壳", "tracking": "J&T: JT888"},
        "12345": {"status": "待付款", "items": "莫奈色系装饰画", "price": "SGD 89"}
    },
    "products": [
        {"id": "p1", "name": "极简几何手机壳", "price": "SGD 25", "style": "包豪斯",
         "img": "https://images.unsplash.com/photo-1603313011101-31c726a54881?w=500"},
        {"name": "手工陶瓷马克杯", "price": "SGD 35", "style": "侘寂",
         "img": "https://images.unsplash.com/photo-1580915411954-282cb1b0d780?w=500"}
    ]
}


# --- 3. 跨平台发送函数 ---
def send_tg(chat_id, text, photo=None):
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: return
    if photo:
        requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                      json={"chat_id": chat_id, "photo": photo, "caption": text, "parse_mode": "Markdown"})
    else:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text})


# --- 4. 商业逻辑工具 ---
def query_order(order_id):
    order = FAKE_DB["orders"].get(order_id)
    if not order: return "No record found."
    if order["status"] == "待付款":
        return f"订单 {order_id} 还在等您付款呢（{order['price']}）。现在下单，我额外送您一张艺术贴纸！"
    return f"订单 {order_id} 状态：{order['status']}。包裹正在路上~"


# --- 5. AI 大脑 ---
def ask_ai(chat_id, text):
    system_prompt = """
# Role
你是一个在东南亚电商界赫赫有名的“金牌导购+销售+客服”。你不仅懂产品，更懂美学和生活方式。

# Tone & Style
1. **地道表达**：你是擅长世界各国语言，尤其是东南亚各国语言，根据用户语言无缝切换，同时保持幽默感。
2. **审美赋能**：你擅长艺术，设计，推销，所以你对颜色、材质、设计有专业见解。不要只报参数，要告诉用户这个产品“怎么美”。
3. **颠覆逻辑**：如果用户嫌贵，不要只给折扣，要告诉他/她“这是一种对生活的投资”。
4. **简介明了**：回答客户的内容简洁明了，大多数客户没有时间看长文字，因此只用回答简洁精华的内容（除非客户要求详细讲解），让用户最容易直接地获取到信息

# Goals
- 解决问题是基础，提供情绪价值和审美建议是核心。
- 引导用户查询订单 (get_order_status) 或推荐产品。
- 如果客户浏览或购买了本商店的商品，可以在客户浏览中或订单结束之后向客户推荐本店其他类似或正在打折有活动的商品。
"""

    tools = [
        {"type": "function", "function": {"name": "get_order",
                                          "parameters": {"type": "object", "properties": {"id": {"type": "string"}},
                                                         "required": ["id"]}}}
    ]

    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
            tools=tools
        )
        msg = res.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                result = query_order(args.get("id"))
                send_tg(chat_id, result)
        else:
            send_tg(chat_id, msg.content)
    except Exception as e:
        send_tg(chat_id, "Aiyoh, wait ah, system a bit slow.")


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and "message" in data:
        ask_ai(data["message"]["chat"]["id"], data["message"].get("text", ""))
    return "ok", 200


@app.route('/')
def home(): return "Commercial AI Agent Active"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))