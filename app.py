import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

# 加载配置
load_dotenv()
app = Flask(__name__)

# --- 1. 核心配置初始化 ---
# 确保在 Railway Variables 中配置了以下所有 Key
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")  # 填入 anon key

# 初始化 Supabase 客户端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 初始化 Grok AI 客户端
client = OpenAI(
    api_key=GROK_KEY,
    base_url="https://api.x.ai/v1"
)
MODEL_NAME = "grok-4-1-fast-reasoning"

# --- 2. 核心商业逻辑提示词 (System Prompt) ---
SYSTEM_PROMPT = """
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


# --- 3. 数据库交互工具函数 ---
def db_get_order(order_id):
    """从 Supabase 查询订单状态"""
    try:
        res = supabase.table("orders").select("*").eq("order_id", order_id).execute()
        if not res.data:
            return f"Aiyoh, 找不到订单 {order_id} 呢，确认一下号码对不对？"
        order = res.data[0]
        return f"找到啦！订单 {order_id} 目前是 [{order['status']}]。商品是：{order['items']}。"
    except Exception as e:
        return f"查询出错啦: {str(e)}"


def db_search_product(query):
    """从 Supabase 搜索产品并返回详细信息"""
    try:
        # 优先搜索名称，其次搜索风格
        res = supabase.table("products").select("*").ilike("name", f"%{query}%").execute()
        if not res.data:
            res = supabase.table("products").select("*").ilike("style", f"%{query}%").execute()

        return res.data if res.data else []
    except Exception as e:
        print(f"DB Search Error: {e}")
        return []


# --- 4. 统一回复函数 ---
def send_reply(chat_id, text, photo_url=None):
    token = os.environ.get("TELEGRAM_TOKEN")
    if photo_url:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo_url, "caption": text, "parse_mode": "Markdown"}
    else:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Post Error: {e}")


# --- 5. AI 大脑逻辑 ---
conversation_history = {}


def ask_ai(chat_id, user_text):
    if chat_id not in conversation_history:
        conversation_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    conversation_history[chat_id].append({"role": "user", "content": user_text})

    # 工具声明
    tools = [
        {"type": "function", "function": {"name": "get_order", "description": "查询订单状态",
                                          "parameters": {"type": "object", "properties": {"id": {"type": "string"}},
                                                         "required": ["id"]}}},
        {"type": "function", "function": {"name": "search_item", "description": "根据关键词或风格搜索产品",
                                          "parameters": {"type": "object", "properties": {"q": {"type": "string"}},
                                                         "required": ["q"]}}}
    ]

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=conversation_history[chat_id],
            tools=tools,
            tool_choice="auto"
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                func_name = call.function.name
                args = json.loads(call.function.arguments)

                if func_name == "get_order":
                    result_text = db_get_order(args.get("id"))
                    send_reply(chat_id, result_text)

                elif func_name == "search_item":
                    items = db_search_product(args.get("q"))
                    if items:
                        item = items[0]
                        caption = f"*{item['name']}* - {item['price']}\n\nStyle: {item['style']}\n_{item['desc']}_"
                        send_reply(chat_id, caption, item['img'])
                    else:
                        send_reply(chat_id, "Aiyoh, 没找到完全匹配的，但看看我们店的其他艺术品？")
            return "Processed"

        # 纯文字回复
        send_reply(chat_id, msg.content)
        conversation_history[chat_id].append(msg)
    except Exception as e:
        send_reply(chat_id, f"Aiyoh, something is wrong: {str(e)}")


# --- 6. 接口适配 ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        ask_ai(chat_id, text)
    return "ok", 200


@app.route('/')
def home():
    return "AI Retail Hub (Supabase Edition) is Active!"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)