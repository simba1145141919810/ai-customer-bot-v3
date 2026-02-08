import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

# 加载配置
load_dotenv()
app = Flask(__name__)

# --- 环境变量配置 ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")

client = OpenAI(
    api_key=GROK_KEY,
    base_url="https://api.x.ai/v1"
)
MODEL_NAME = "grok-4-1-fast-reasoning"


# --- 统一发送接口 ---
def send_tg(chat_id, text, photo=None):
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: return

    if photo:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo, "caption": text or "", "parse_mode": "Markdown"}
    else:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Send Error: {e}")


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        user_text = data["message"].get("text", "")

        try:
            res = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "system", "content": "你是一个地道的东南亚艺术导购。"},
                          {"role": "user", "content": user_text}]
            )
            send_tg(chat_id, res.choices[0].message.content)
        except Exception as e:
            send_tg(chat_id, f"Aiyoh, something wrong: {str(e)}")

    return "ok", 200


@app.route('/')
def home():
    return "AI Retail Hub Active"


if __name__ == '__main__':
    # 强制绑定 0.0.0.0 和 Railway 端口
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)