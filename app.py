import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
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

# --- 2. 模拟数据库 (包含图片链接) ---
FAKE_ORDERS = {
    "14514": {"status": "已发货", "tracking": "J&T Express: JT123456", "items": "极简几何手机壳"},
    "12345": {"status": "处理中", "items": "莫奈色系装饰画"}
}

FAKE_PRODUCTS = [
    {
        "name": "极简几何手机壳",
        "price": "SGD 25",
        "style": "包豪斯主义",
        "desc": "线条利落，适合追求理性的你。配合侘寂风桌面绝佳。",
        "img": "https://images.unsplash.com/photo-1603313011101-31c726a54881?auto=format&fit=crop&w=500&q=80"
    },
    {
        "name": "莫奈色系装饰画",
        "price": "SGD 89",
        "style": "印象派",
        "desc": "色彩柔和，能瞬间提升客厅的艺术氛围。",
        "img": "https://images.unsplash.com/photo-1579783902614-a3fb3927b6a5?auto=format&fit=crop&w=500&q=80"
    },
    {
        "name": "手工陶瓷马克杯",
        "price": "SGD 35",
        "style": "侘寂风",
        "desc": "不完美的肌理，触感温润，每一件都是独一无二。",
        "img": "https://images.unsplash.com/photo-1580915411954-282cb1b0d780?auto=format&fit=crop&w=500&q=80"
    }
]


# --- 3. 辅助函数：专门发送图片到 Telegram ---
def send_telegram_photo(chat_id, photo_url, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"发送图片失败: {e}")


# --- 4. 存储对话历史 ---
conversation_history = {}

# --- 5. 系统提示词 ---
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

# Rules
- 用户问推荐、对比、或寻找某类风格时，必须调用 search_products。
- 用户查进度时，必须调用 get_order_status。
"""

# --- 6. 工具定义 ---
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
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "搜索产品推荐、风格匹配或艺术单品",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }
]


# --- 7. 工具逻辑实现 ---
def call_tool(func_name, args, chat_id):
    if func_name == "get_order_status":
        order_id = args.get("order_number")
        return str(FAKE_ORDERS.get(order_id, "Sorry, no record for this order number leh."))

    if func_name == "search_products":
        query = args.get("query", "").lower()
        results = [p for p in FAKE_PRODUCTS if query in p['name'].lower() or query in p['style'].lower()]

        if results:
            target = results[0]
            # 找到产品，立刻触发发图
            caption = f"*{target['name']}*\nPrice: {target['price']}\nStyle: {target['style']}"
            send_telegram_photo(chat_id, target['img'], caption)
            return f"Found it! 我已经把图片的预览发给你了。这是我们的{target['name']}，{target['desc']}"

        return "Aiyoh, nothing exact match, but check our latest Art Series: " + str(FAKE_PRODUCTS[0])

    return "Unknown tool."


# --- 8. AI 核心逻辑 ---
def ask_grok(chat_id, user_input):
    if chat_id not in conversation_history:
        conversation_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    conversation_history[chat_id].append({"role": "user", "content": user_input})

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=conversation_history[chat_id],
            tools=tools,
            tool_choice="auto"
        )

        msg = response.choices[0].message

        if msg.tool_calls:
            conversation_history[chat_id].append(msg)
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                # 注意这里传入了 chat_id 以便发图
                result = call_tool(func_name, args, chat_id)

                conversation_history[chat_id].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": result
                })

            second_res = client.chat.completions.create(
                model=MODEL_NAME,
                messages=conversation_history[chat_id]
            )
            final_reply = second_res.choices[0].message.content
        else:
            final_reply = msg.content
    except Exception as e:
        final_reply = f"Aiyoh, error: {str(e)}"

    conversation_history[chat_id].append({"role": "assistant", "content": final_reply})
    return final_reply


# --- 9. 接口定义 ---
@app.route('/')
def home():
    return "Universal Art-AI Bot is Running!"


@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if data and "message" in data:
        chat_id = str(data["message"]["chat"]["id"])
        text = data["message"].get("text", "")
        reply = ask_grok(chat_id, text)

        # 发送文本回复
        send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(send_url, json={"chat_id": chat_id, "text": reply})
    return "ok", 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)