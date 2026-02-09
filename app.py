import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- 极简配置检查 ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
print(f"--- SYSTEM STARTUP CHECK: TOKEN EXISTS = {bool(TOKEN)} ---")


def quick_reply(chat_id, text):
    """最底层的发送测试"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
        print(f"Quick Reply Status: {r.status_code}")
    except Exception as e:
        print(f"Quick Reply Failed: {e}")


@app.route('/webhook', methods=['POST'])
def webhook():
    # 只要有请求进来，无论如何先回一个“收到”
    data = request.get_json()
    print(f"Incoming Data: {data}")  # 这行会在 Railway Log 打印出收到的消息原文

    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        # 强制回复，跳过所有 AI 逻辑，测试通道是否通畅
        quick_reply(chat_id, "System online. I received your message.")
    return "ok", 200


@app.route('/')
def home():
    return f"Bot Status: {bool(TOKEN)}"


if __name__ == '__main__':
    # 强制使用 Railway 要求的 8080 端口和 0.0.0.0
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)