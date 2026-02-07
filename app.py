import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from openai import OpenAI
import requests
import json

load_dotenv()

app = Flask(__name__)

# Zetpy 配置（在 Zetpy 后台获取）
ZETPY_WEBHOOK_TOKEN = os.getenv("ZETPY_WEBHOOK_TOKEN")  # Zetpy 提供的验证 token
ZETPY_API_KEY = os.getenv("ZETPY_API_KEY")  # Zetpy API key，用于发送回复

# Grok 配置
GROK_API_KEY = os.getenv("GROK_API_KEY")
OPENAI_API_KEY = GROK_API_KEY  # 兼容 SDK 检查

client = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

MODEL_NAME = "grok-4-1-fast-reasoning"

# --------------------- 模拟数据库（测试用） ---------------------
FAKE_ORDERS = {
    "14514": {"status": "已发货", "tracking": "J&T Express: JT123456", "items": "Redmi Note 12"},
    "12345": {"status": "处理中", "tracking": "未生成", "items": "Samsung A14"},
    "99999": {"status": "已退货", "tracking": "退款中", "items": "鞋子"}
}

FAKE_PRODUCTS = [
    {"name": "Redmi Note 12", "price": "SGD 299", "specs": "120Hz屏, 5000mAh电池, 骁龙处理器"},
    {"name": "Realme C55", "price": "SGD 189", "specs": "大电池快充, 自拍强"},
    {"name": "Samsung A14", "price": "SGD 219", "specs": "三星品质, 拍照稳"},
    {"name": "iPhone 13", "price": "SGD 999", "specs": "苹果生态, 性能顶"},
    {"name": "Running Shoes", "price": "SGD 89", "specs": "轻便透气, 适合跑步"}
]

# --------------------- 工具定义 ---------------------
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


# --------------------- 工具函数 ---------------------
def get_order_status(order_number: str):
    order = FAKE_ORDERS.get(order_number)
    if order:
        return f"订单 {order_number}：{order['status']}，商品 {order['items']}，追踪 {order['tracking']}。"
    return f"未找到订单 {order_number}，请确认订单号或联系人工。"


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


# --------------------- 系统提示词 ---------------------
SYSTEM_PROMPT = """
你是一个专业的东南亚电商客服机器人，使用 Grok 的聪明和幽默。
用用户语言回复（中文、英文、印尼语、泰语等）。
用户问推荐/替代/便宜/手机等，必须优先调用 search_products 工具。
订单号必须调用 get_order_status。
回复自然、简洁，像真人。
"""

conversation_history = {}


# --------------------- Zetpy webhook ---------------------
@app.route('/zetpy_webhook', methods=['POST'])
def zetpy_webhook():
    # 验证 Zetpy token
    if request.headers.get('X-Zetpy-Token') != ZETPY_WEBHOOK_TOKEN:
        return jsonify({"error": "invalid token"}), 401

    data = request.get_json()
    print("收到 Zetpy 消息:", json.dumps(data, ensure_ascii=False, indent=2))

    # Zetpy 消息结构（简化处理，实际根据文档调整）
    if 'messages' in data and data['messages']:
        for msg in data['messages']:
            conversation_id = msg.get('conversation_id') or msg.get('chat_id')
            user_text = msg.get('text', '')
            platform = msg.get('platform', 'unknown')

            if not conversation_id or not user_text:
                continue

            # 初始化对话历史
            if conversation_id not in conversation_history:
                conversation_history[conversation_id] = [
                    {"role": "system", "content": SYSTEM_PROMPT + f" (平台: {platform})"}]

            conversation_history[conversation_id].append({"role": "user", "content": user_text})

            # 调用 Grok
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=conversation_history[conversation_id],
                tools=tools,
                tool_choice="auto",
                max_tokens=512,
                temperature=0.7
            )

            message = response.choices[0].message
            reply_text = message.content or ""

            # 处理工具调用
            if message.tool_calls:
                tool_results = ""
                for tool_call in message.tool_calls:
                    func_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    query = args.get("query") or args.get("order_number", "")

                    if func_name == "get_order_status":
                        result = get_order_status(query)
                    elif func_name == "search_products":
                        result = search_products(query)

                    tool_results += f"\n\n{result}"

                    conversation_history[conversation_id].append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": result
                    })

                # 二次调用整合
                second_response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=conversation_history[conversation_id],
                    max_tokens=512
                )
                reply_text = second_response.choices[0].message.content + tool_results

            # 回复 Zetpy
            zetpy_reply = {
                "conversation_id": conversation_id,
                "text": reply_text
            }
            headers = {
                "Authorization": f"Bearer {ZETPY_API_KEY}",
                "Content-Type": "application/json"
            }
            resp = requests.post("https://api.zetpy.com/v1/messages/send", json=zetpy_reply, headers=headers)
            print("Zetpy send response:", resp.status_code, resp.text)

    return jsonify({"status": "ok"})


@app.route('/')
def home():
    return "Zetpy + Grok AI Bot is running!"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)