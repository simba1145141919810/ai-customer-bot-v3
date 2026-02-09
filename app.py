import os
import json
import requests
import time
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)


# --- 1. 配置加载 (直接从环境读取，防止作用域错误) ---
def get_env(key):
    val = os.environ.get(key)
    if not val:
        print(f"CRITICAL ERROR: {key} is missing!")
    return val


TG_TOKEN = get_env("TELEGRAM_TOKEN")
GROK_KEY = get_env("GROK_API_KEY")
SUPABASE_URL = get_env("SUPABASE_URL")
SUPABASE_KEY = get_env("SUPABASE_KEY")

# 初始化客户端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")
MODEL_NAME = "grok-3"  # 强制使用最稳定的模型名


# --- 2. 辅助功能 ---

def set_typing(chat_id):
    """显示正在输入状态"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendChatAction"
    requests.post(url, json={"chat_id": chat_id, "action": "typing"})


def send_reply(chat_id, text, photo_url=None, buy_url=None):
    """增强版回复函数：支持图片、文字和购买按钮"""
    reply_markup = None
    if buy_url:
        reply_markup = {"inline_keyboard": [[{"text": "🛒 点击直接购买 (Buy Now)", "url": buy_url}]]}

    if photo_url and photo_url.startswith("http"):
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo_url, "caption": text, "parse_mode": "Markdown",
                   "reply_markup": reply_markup}
    else:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": reply_markup}

    try:
        r = requests.post(url, json=payload, timeout=10)
        print(f"Telegram Post Result: {r.status_code}")
    except Exception as e:
        print(f"Send Error: {e}")


# --- 3. 数据库逻辑 (适配表名 orders) ---

def db_get_order(order_id):
    try:
        # 确保这里使用你刚刚更改的复数表名 orders
        res = supabase.table("orders").select("*").eq("order_id", str(order_id)).execute()
        if not res.data:
            return f"Aiyoh, 找不到订单 {order_id} 呢。检查一下号码？"
        order = res.data[0]
        return f"找到了！订单 {order_id} 状态：*[{order['status']}]*。物流：{order.get('tracking', '处理中')}。"
    except Exception as e:
        return f"数据库连接报错啦: {str(e)}"


def db_search_product(query):
    try:
        res = supabase.table("products").select("*").ilike("name", f"%{query}%").execute()
        if not res.data:
            res = supabase.table("products").select("*").ilike("style", f"%{query}%").execute()
        return res.data if res.data else []
    except Exception as e:
        print(f"Product DB Error: {e}")
        return []


# --- 4. AI 逻辑处理 ---
conversation_history = {}
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

# Rules
1. **订单查询逻辑**：如果用户说要查订单但没给订单号，你必须先礼貌地询问订单号，**严禁直接推荐产品**。
2. **产品搜索逻辑**：只有当用户表达了购买意向、审美偏好或寻找特定产品时，才调用 search_item。
"""


def ask_ai(chat_id, user_text):
    if chat_id not in conversation_history:
        conversation_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    conversation_history[chat_id].append({"role": "user", "content": user_text})
    set_typing(chat_id)

    tools = [
        {"type": "function", "function": {"name": "get_order", "description": "查询订单状态",
                                          "parameters": {"type": "object", "properties": {"id": {"type": "string"}},
                                                         "required": ["id"]}}},
        {"type": "function", "function": {"name": "search_item", "description": "根据关键词搜索产品",
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
                    reply = db_get_order(args.get("id"))
                    send_reply(chat_id, reply)
                elif func_name == "search_item":
                    items = db_search_product(args.get("q"))
                    if items:
                        item = items[0]
                        cap = f"*{item['name']}* - {item['price']}\n\nStyle: {item['style']}\n_{item.get('desc', '')}_"
                        send_reply(chat_id, cap, item.get('img'), item.get('buy_url'))
                    else:
                        send_reply(chat_id, "抱歉，没找到这款宝贝。")
            return

        # 兜底纯文本回复
        send_reply(chat_id, msg.content)
        conversation_history[chat_id].append(msg)
    except Exception as e:
        print(f"Final AI Logic Error: {e}")
        send_reply(chat_id, "系统有点累，请重试一次 lah!")


# --- 5. 接口 ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and "message" in data:
        ask_ai(data["message"]["chat"]["id"], data["message"].get("text", ""))
    return "ok", 200


@app.route('/')
def home(): return "Commercial AI Agent is Online!"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)