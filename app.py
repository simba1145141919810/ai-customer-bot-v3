import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 配置加载 ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")

# --- 商业级提示词 (System Prompt) ---
PROMPT = """
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
- 查单：必须调用 get_order
- 搜货：必须调用 search_product
"""


# --- 发送函数 ---
def safe_send(chat_id, text, photo=None, buy_url=None):
    reply_markup = None
    if buy_url:
        reply_markup = {"inline_keyboard": [[{"text": "🛒 点击直接购买 (Buy Now)", "url": buy_url}]]}

    if photo and photo.startswith("http"):
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo, "caption": text, "parse_mode": "Markdown",
                   "reply_markup": reply_markup}
    else:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": reply_markup}

    try:
        requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
    except Exception as e:
        print(f"Send Error: {e}")


# --- 数据库函数 (使用测试成功的底层请求) ---
def db_get_order(order_id):
    url = f"{SUPABASE_URL}/rest/v1/orders?order_id=eq.{order_id}&select=*"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        res = requests.get(url, headers=headers, timeout=5).json()
        if res:
            o = res[0]
            return f"✅ **Order Check Success**\nOrder ID: `{order_id}`\nStatus: {o.get('status')}\nTracking: {o.get('tracking')}"
        return f"❌ Aiyoh, 找不到订单号 {order_id} 呢。"
    except:
        return "System busy, try again later lah."


def db_search_product(query):
    url = f"{SUPABASE_URL}/rest/v1/products?or=(name.ilike.*{query}*,style.ilike.*{query}*)&select=*"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        return requests.get(url, headers=headers, timeout=5).json()
    except:
        return []


# --- Webhook ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    user_text = data["message"].get("text", "").strip()

    # 查单拦截器 (保持稳定性)
    if user_text.isdigit():
        safe_send(chat_id, db_get_order(user_text))
        return "ok", 200

    # Grok AI 导购
    try:
        tools = [
            {"type": "function", "function": {"name": "search_product", "parameters": {"type": "object", "properties": {
                "q": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "get_order", "parameters": {"type": "object", "properties": {
                "id": {"type": "string"}}}}}
        ]

        response = client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": user_text}
            ],
            tools=tools
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                if call.function.name == "get_order":
                    safe_send(chat_id, db_get_order(args.get("id")))
                elif call.function.name == "search_product":
                    items = db_search_product(args.get("q"))
                    if items:
                        item = items[0]
                        text = f"*{item['name']}* - {item['price']}\n\n_{item.get('desc', '')}_"
                        safe_send(chat_id, text, item.get('img'), item.get('buy_url'))
                    else:
                        safe_send(chat_id, "Wait ah, 没搜到这个宝贝，看看其他的？")
        else:
            safe_send(chat_id, msg.content)

    except Exception as e:
        # 即使 AI 报错，也给客户一个礼貌的回应
        safe_send(chat_id, "Aiyoh, system a bit tired. Just send me your Order ID directly can?")

    return "ok", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))