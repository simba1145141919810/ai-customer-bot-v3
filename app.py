import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from openai import OpenAI
import requests
import json

load_dotenv()

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")
OPENAI_API_KEY = GROK_API_KEY  # 兼容 SDK 检查

client = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

MODEL_NAME = "grok-4-1-fast-reasoning"

# 模拟订单数据库
FAKE_ORDERS = {
    "14514": {"status": "已发货", "tracking": "J&T Express: JT123456", "items": "Redmi Note 12"},
    "12345": {"status": "处理中", "tracking": "未生成", "items": "Samsung A14"},
    "99999": {"status": "已退货", "tracking": "退款中", "items": "鞋子"}
}

# 模拟商品数据库
FAKE_PRODUCTS = [
    {"name": "Redmi Note 12", "price": "SGD 299", "specs": "120Hz屏, 5000mAh电池, 骁龙处理器"},
    {"name": "Realme C55", "price": "SGD 189", "specs": "大电池快充, 自拍强, 便宜替代"},
    {"name": "Samsung A14", "price": "SGD 219", "specs": "三星品质, 拍照稳, 性价比高"},
    {"name": "iPhone 13", "price": "SGD 999", "specs": "苹果生态, 性能顶"},
    {"name": "Running Shoes", "price": "SGD 89", "specs": "轻便透气, 适合跑步"}
]

# 工具定义
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "查询订单状态，需要订单号",
            "parameters": {
                "type": "object",
                "properties": {"order_number": {"type": "string"}},
                "required": ["order_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "用户问产品推荐、替代、更便宜等，必须调用此工具搜索商品库",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }
]


def get_order_status(order_number: str):
    order = FAKE_ORDERS.get(order_number)
    if order:
        return f"订单 {order_number}：{order['status']}，商品 {order['items']}，追踪 {order['tracking']}。"
    return f"未找到订单 {order_number}。"


def search_products(query: str):
    query_lower = query.lower()
    keywords = query_lower.split()
    matches = []
    for p in FAKE_PRODUCTS:
        if any(k in p["name"].lower() or k in p["specs"].lower() for k in
               keywords) or "便宜" in query_lower or "替代" in query_lower:
            matches.append(p)
    if not matches:
        return "抱歉，没找到完美匹配，但可以看看这些热门商品。"

    rec = "为您推荐这些：\n"
    for i, p in enumerate(matches[:5], 1):
        rec += f"{i}. {p['name']} - {p['price']}\n   {p['specs']}\n"
    return rec


SYSTEM_PROMPT = """
你是一个专业的东南亚电商客服机器人，使用 Grok 的聪明和幽默。
用用户语言回复。
用户问推荐/替代/便宜/手机等，必须优先调用 search_products 工具。
订单号必须调用 get_order_status。
回复自然、简洁，像真人。
"""

conversation_history = {}


@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()

    if 'message' in update:
        chat_id = update['message']['chat']['id']
        user_text = update['message'].get('text', '')

        if chat_id not in conversation_history:
            conversation_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

        conversation_history[chat_id].append({"role": "user", "content": user_text})

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=conversation_history[chat_id],
            tools=tools,
            tool_choice="auto",
            max_tokens=512,
            temperature=0.7
        )

        message = response.choices[0].message
        reply_text = message.content or ""

        if message.tool_calls:
            tool_results = ""
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                query = args.get("query") or args.get("order_number", "")

                if func_name == "get_order_status":
                    result = get_order_status(query)
                else:
                    result = search_products(query)

                tool_results += f"\n\n{result}"

                conversation_history[chat_id].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": result
                })

            second_response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=conversation_history[chat_id],
                max_tokens=512,
                temperature=0.7
            )
            reply_text = second_response.choices[0].message.content + tool_results

        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": reply_text})

    return jsonify({"status": "ok"})


@app.route('/')
def home():
    return "Bot is running!"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # 云平台端口适配
    app.run(host='0.0.0.0', port=port)