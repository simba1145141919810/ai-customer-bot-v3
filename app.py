import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 1. 配置加载 (只需两个 Key) ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")

client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")


# --- 2. 核心：加载本地 JSON 数据 ---
def load_local_data():
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading data.json: {e}")
        return {"products": [], "orders": {}}


# --- 3. 稳健的发送函数 ---
def safe_send(chat_id, text, photo=None, buy_url=None):
    reply_markup = None
    if buy_url:
        reply_markup = {"inline_keyboard": [[{"text": "🛒 点击直接购买 (Buy Now)", "url": buy_url}]]}

    headers = {"Content-Type": "application/json"}

    if photo and photo.startswith("http"):
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo, "caption": text, "parse_mode": "Markdown",
                   "reply_markup": reply_markup}
    else:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": reply_markup}

    try:
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print(f"Telegram API Error: {e}")


# --- 4. Webhook 核心逻辑 ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    user_text = data["message"].get("text", "").strip()
    db = load_local_data()

    # 逻辑 1：查单拦截器 (直接读取本地 JSON)
    if user_text.isdigit():
        order = db["orders"].get(user_text)
        if order:
            res_text = f"✅ **查到啦！**\n单号：`{user_text}`\n状态：{order['status']}\n物品：{order['items']}\n物流：{order['tracking']}"
        else:
            res_text = f"❌ Aiyoh, 找不到订单号 {user_text} 呢。"
        safe_send(chat_id, res_text)
        return "ok", 200

    # 逻辑 2：Grok AI 导购
    try:
        response = client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[
                {"role": "system", "content": "你是一个地道的东南亚艺术导购。"},
                {"role": "user", "content": user_text}
            ],
            timeout=15
        )
        ai_reply = response.choices[0].message.content

        # 简单的关键词触发搜货逻辑 (比 Tool Call 更稳)
        found_product = False
        for p in db["products"]:
            if p["name"] in user_text or p["style"] in user_text:
                text = f"*{p['name']}* - {p['price']}\n\n{p['desc']}\n\n{ai_reply}"
                safe_send(chat_id, text, p['img'], p['buy_url'])
                found_product = True
                break

        if not found_product:
            safe_send(chat_id, ai_reply)

    except Exception as e:
        safe_send(chat_id, "Aiyoh, 客服小助手有点累，请直接输入订单号查询。")

    return "ok", 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)