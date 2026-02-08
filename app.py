import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from openai import OpenAI
import requests
import json

load_dotenv()

app = Flask(__name__)

# Grok 配置
GROK_API_KEY = os.getenv("GROK_API_KEY")
OPENAI_API_KEY = GROK_API_KEY  # SDK兼容

client = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

MODEL_NAME = "grok-4-1-fast-reasoning"

# 模拟数据库（真实部署时替换为Shopee/Lazada API）
FAKE_ORDERS = {
    "14514": {
        "status": "已发货",
        "tracking": "J&T Express: JT123456",
        "items": "Redmi Note 12",
        "image_url": "https://example.com/images/redmi_note12.jpg"  # 店铺真实产品图
    },
    "12345": {
        "status": "处理中",
        "tracking": "未生成",
        "items": "Samsung A14",
        "image_url": "https://example.com/images/samsung_a14.jpg"
    },
    "99999": {
        "status": "已退货",
        "tracking": "退款中",
        "items": "Running Shoes",
        "image_url": "https://example.com/images/running_shoes.jpg"
    }
}

FAKE_PRODUCTS = [
    {
        "name": "Redmi Note 12",
        "price": "SGD 299",
        "specs": "120Hz屏, 5000mAh电池, 骁龙处理器",
        "image_url": "https://example.com/images/redmi_note12.jpg"
    },
    {
        "name": "Realme C55",
        "price": "SGD 189",
        "specs": "大电池快充, 自拍强",
        "image_url": "https://example.com/images/realme_c55.jpg"
    },
    {
        "name": "Samsung A14",
        "price": "SGD 219",
        "specs": "三星品质, 拍照稳",
        "image_url": "https://example.com/images/samsung_a14.jpg"
    },
    {
        "name": "iPhone 13",
        "price": "SGD 999",
        "specs": "苹果生态, 性能顶",
        "image_url": "https://example.com/images/iphone13.jpg"
    },
    {
        "name": "Running Shoes",
        "price": "SGD 89",
        "specs": "轻便透气, 适合跑步",
        "image_url": "https://example.com/images/running_shoes.jpg"
    }
]

# 工具定义（新增获取真实产品图片）
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "查询订单状态，返回文字+产品真实图片",
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
            "description": "搜索并推荐产品，返回列表+每件商品真实图片",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_product_image",
            "description": "生成产品场景图（如搭配图、效果图）",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"]
            }
        }
    }
]


def get_order_status(order_number: str):
    order = FAKE_ORDERS.get(order_number)
    if order:
        text = f"订单 {order_number}：{order['status']}，商品 {order['items']}，追踪 {order['tracking']}。"
        return json.dumps({"text": text, "image_url": order.get("image_url")})
    return json.dumps({"text": f"未找到订单 {order_number}。", "image_url": None})


def search_products(query: str):
    query_lower = query.lower()
    keywords = query_lower.split()
    matches = []
    for p in FAKE_PRODUCTS:
        if any(k in p["name"].lower() or k in p["specs"].lower() for k in
               keywords) or "便宜" in query_lower or "替代" in query_lower:
            matches.append(p)
    if not matches:
        return json.dumps({"text": "抱歉，没找到匹配商品。", "images": []})

    text = "为您推荐这些：\n"
    images = []
    for i, p in enumerate(matches[:5], 1):
        text += f"{i}. {p['name']} - {p['price']}\n   {p['specs']}\n"
        if p.get("image_url"):
            images.append(p["image_url"])

    return json.dumps({"text": text, "images": images})


def generate_product_image(prompt: str):
    try:
        response = client.images.generate(
            model="flux",
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        image_url = response.data[0].url
        return json.dumps({"text": "为您生成场景图：", "image_url": image_url})
    except Exception as e:
        return json.dumps({"text": f"生成失败：{str(e)}", "image_url": None})


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

conversation_history = {}


def send_telegram_message(chat_id, text=None, photo=None):
    if photo:
        payload = {"chat_id": chat_id, "photo": photo, "caption": text or ""}
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", json=payload)
    elif text:
        payload = {"chat_id": chat_id, "text": text}
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload)


@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()

    if 'message' in update:
        chat_id = update['message']['chat']['id']
        user_text = update['message'].get('text', '')

        if chat_id not in conversation_history:
            conversation_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

        conversation_history[chat_id].append({"role": "user", "content": user_text})

        try:
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

            images = []
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    func_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)

                    result_str = ""
                    if func_name == "get_order_status":
                        result_str = get_order_status(args["order_number"])
                    elif func_name == "search_products":
                        result_str = search_products(args["query"])
                    elif func_name == "generate_product_image":
                        result_str = generate_product_image(args["prompt"])

                    result = json.loads(result_str)
                    reply_text += f"\n{result.get('text', '')}"
                    image_url = result.get('image_url')
                    if image_url:
                        images.append(image_url)
                    img_list = result.get('images', [])
                    if img_list:
                        images.extend(img_list)

                    conversation_history[chat_id].append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": result_str
                    })

                # 二次调用整合文字
                second_response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=conversation_history[chat_id],
                    max_tokens=512
                )
                reply_text = second_response.choices[0].message.content

            # 发送：优先图片+文字，其次纯文字
            if images:
                # 发送第一张图+文字，其他图单独发（Telegram限制）
                send_telegram_message(chat_id, reply_text, images[0])
                for img in images[1:]:
                    send_telegram_message(chat_id, None, img)
            else:
                send_telegram_message(chat_id, reply_text)

        except Exception as e:
            send_telegram_message(chat_id, "抱歉，系统出错，请稍后再试。")

    return jsonify({"status": "ok"})


@app.route('/')
def home():
    return "Bot running!"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)