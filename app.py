import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- 1. 严格变量获取 ---
# 无论如何，这里必须拿到 Token
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def log_and_send(chat_id, text):
    """
    最底层的发送函数，带有极强的日志追踪
    """
    if not TELEGRAM_TOKEN:
        print("CRITICAL: TELEGRAM_TOKEN IS MISSING IN ENV!")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        # 这行会在 Railway 日志里打印 Telegram 的真实回执
        print(f"Telegram API Response: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Request Error: {e}")


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"DEBUG INCOMING: {json.dumps(data)}")  # 监控原始数据

        if data and "message" in data:
            chat_id = data["message"]["chat"]["id"]
            user_text = data["message"].get("text", "")

            # 只要是数字，绕过所有逻辑直接查数据库并回传
            if user_text.isdigit():
                print(f"Processing Order ID: {user_text}")
                # 暂时跳过 Supabase 库，用最原始的 requests 查，防止库冲突
                db_url = f"{SUPABASE_URL}/rest/v1/orders?order_id=eq.{user_text}&select=*"
                db_headers = {
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}"
                }
                db_res = requests.get(db_url, headers=db_headers, timeout=5)

                if db_res.status_code == 200 and db_res.json():
                    order = db_res.json()[0]
                    msg = f"✅ Order Found: {user_text}\nStatus: {order.get('status')}\nTracking: {order.get('tracking')}"
                else:
                    msg = f"❌ Order {user_text} not found or DB Error."

                log_and_send(chat_id, msg)
            else:
                log_and_send(chat_id, f"I received: {user_text}. Please send a digital order ID.")

    except Exception as e:
        print(f"Webhook Crash: {e}")

    return "ok", 200


@app.route('/')
def home():
    return "Ready to serve."


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)