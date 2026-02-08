import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

# 加载本地环境变量
load_dotenv()

app = Flask(__name__)

# --- 1. 配置初始化 ---
GROK_API_KEY = os.getenv("GROK_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

MODEL_NAME = "grok-4-1-fast-reasoning"

# --- 2. 模拟数据库 (未来接入真实 API) ---
FAKE_ORDERS = {
    "14514": {"status": "已发货", "tracking": "J&T Express: JT123456", "items": "Redmi Note 12"},
    "12345": {"status": "处理中", "items": "Samsung A14"}
}

# --- 3. 存储对话历史 (简单内存存储，重启后重置) ---
# 在生产环境中，我们会改用 Redis 来永久存储
conversation_history = {}

# --- 4. 系统提示词 (System Prompt) ---
# 这里是颠覆逻辑的核心：赋予 AI 审美眼光和本地灵魂
SYSTEM_PROMPT = """
# Role
你是一个在东南亚电商界赫赫有名的“金牌导购+销售+客服”。你不仅懂产品，更懂美学和生活方式。

# Tone & Style
1. **地道表达**：你是擅长世界各国语言，尤其是东南亚各国语言，根据用户语言无缝切换，同时保持幽默感。
2. **审美赋能**：你擅长艺术，设计，推销，所以你对颜色、材质、设计有专业见解。不要只报参数，要告诉用户这个产品“怎么美”。
3. **颠覆逻辑**：如果用户嫌贵，不要只给折扣，要告诉他/她“这是一种对生活的投资”。

# Goals
- 解决问题是基础，提供情绪价值和审美建议是核心。
- 引导用户查询订单 (get_order_status) 或推荐产品。
- 如果客户浏览或购买了本商店的商品，可以在客户浏览中或订单结束之后向客户推荐本店其他类似或正在打折有活动的商品。
"""

# --- 5. 工具定义 ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "查询订单实时状态",
            "parameters": {
                "type": "object",
                "properties": {"order_number": {"type": "string"}},
                "required": ["order_number"]
            }
        }
    }
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


# --- 6. AI 核心逻辑 ---
def ask_grok(chat_id, user_input):
    # 初始化历史记录
    if chat_id not in conversation_history:
        conversation_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 加入用户新消息
    conversation_history[chat_id].append({"role": "user", "content": user_input})

    # 限制历史长度，防止超过 Token 限制
    if len(conversation_history[chat_id]) > 10:
        conversation_history[chat_id] = [conversation_history[chat_id][0]] + conversation_history[chat_id][-9:]

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=conversation_history[chat_id],
        tools=tools,
        tool_choice="auto"
    )

    msg = response.choices[0].message

    # 处理工具调用
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            order_id = args.get("order_number")
            result = FAKE_ORDERS.get(order_id, "Sorry, order not found leh.")

            # 将结果喂回给 AI
            conversation_history[chat_id].append(msg)
            conversation_history[chat_id].append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": "get_order_status",
                "content": str(result)
            })

            second_res = client.chat.completions.create(
                model=MODEL_NAME,
                messages=conversation_history[chat_id]
            )
            final_reply = second_res.choices[0].message.content
    else:
        final_reply = msg.content

    # 保存 AI 的回复到历史
    conversation_history[chat_id].append({"role": "assistant", "content": final_reply})
    return final_reply


# --- 7. 接口定义 ---
@app.route('/')
def home():
    return "SE-Asia AI Agent is Running!"


@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if "message" in data:
        chat_id = str(data["message"]["chat"]["id"])
        text = data["message"].get("text", "")

        reply = ask_grok(chat_id, text)

        send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(send_url, json={"chat_id": chat_id, "text": reply})
    return "ok", 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)