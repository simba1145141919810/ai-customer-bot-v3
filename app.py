import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

# 加载本地 .env 文件中的变量
load_dotenv()

app = Flask(__name__)

# --- 1. 配置初始化 ---
# 这里的变量名必须与你在 Railway 后台 Variables 设置的一致
GROK_API_KEY = os.getenv("GROK_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

# 使用适合对话的 Grok 模型
MODEL_NAME = "grok-4-1-fast-reasoning"

# --- 2. 模拟数据库 (以后可以连接真实数据库) ---
FAKE_ORDERS = {
    "14514": {"status": "已发货", "tracking": "J&T Express: JT123456", "items": "Redmi Note 12"},
    "12345": {"status": "处理中", "tracking": "未生成", "items": "Samsung A14"}
}

FAKE_PRODUCTS = [
    {"name": "Redmi Note 12", "price": "SGD 299", "specs": "120Hz屏, 5000mAh电池"},
    {"name": "Samsung A14", "price": "SGD 219", "specs": "三星品质, 拍照稳"}
]


# --- 3. AI 工具函数定义 ---
def get_order_status(order_number: str):
    order = FAKE_ORDERS.get(order_number)
    if order:
        return f"订单 {order_number}：{order['status']}，物流：{order['tracking']}。"
    return f"抱歉，没找到订单 {order_number}。"


def search_products(query: str):
    # 简单的搜索逻辑
    return f"为您找到关于 '{query}' 的产品：Redmi Note 12 (SGD 299)。"


# AI 可以调用的工具声明
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "查询订单状态",
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
            "description": "搜索产品推荐",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }
]


# --- 4. 核心 AI 处理引擎 ---
# 这个函数是通用的，不分平台
def ask_grok(user_input):
    messages = [
        {"role": "system", "content": "你是一个地道的东南亚电商客服，说话亲切，偶尔可以用 Singlish。"},
        {"role": "user", "content": user_input}
    ]

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    response_message = response.choices[0].message

    # 如果 AI 决定调用工具
    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            function_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            if function_name == "get_order_status":
                result = get_order_status(args.get("order_number"))
            else:
                result = search_products(args.get("query"))

            # 将工具结果返回给 AI 进行最终润色
            messages.append(response_message)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": function_name, "content": result})

            second_response = client.chat.completions.create(model=MODEL_NAME, messages=messages)
            return second_response.choices[0].message.content

    return response_message.content


# --- 5. 接口路由 ---

# 首页，用于检查服务是否在线
@app.route('/')
def home():
    return "AI Bot is Online!"


# Telegram 专用 Webhook 接口
@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        user_text = data["message"].get("text", "")

        # 获取 AI 回复
        reply = ask_grok(user_text)

        # 发送回 Telegram
        send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(send_url, json={"chat_id": chat_id, "text": reply})

    return "ok", 200


# 通用 API 接口 (以后给其他软件用)
@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json()
    msg = data.get("message")
    reply = ask_grok(msg)
    return jsonify({"reply": reply})


if __name__ == '__main__':
    # 自动适配端口
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)