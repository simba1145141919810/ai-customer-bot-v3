import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 核心变量加载 ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 初始化客户端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")


# --- 强力发送函数 ---
def send_debug_msg(chat_id, text, photo=None, url=None):
    """无论发生什么，都强制回传信息"""
    reply_markup = {"inline_keyboard": [[{"text": "🛒 Buy Now", "url": url}]]} if url else None

    if photo and photo.startswith("http"):
        api_url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo, "caption": text, "parse_mode": "Markdown",
                   "reply_markup": reply_markup}
    else:
        api_url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": reply_markup}

    requests.post(api_url, json=payload, timeout=10)


# --- 暴力数据库查询 ---
def db_get_order(order_id):
    order_str = str(order_id).strip()
    try:
        # 依次尝试所有可能的表名，防止单复数纠纷
        for table in ["orders", "order"]:
            print(f"DEBUG: Trying table {table} with id {order_str}")
            res = supabase.table(table).select("*").eq("order_id", order_id).execute()
            if res.data:
                o = res.data[0]
                return f"✅ 找到订单！\n单号：{order_str}\n状态：{o.get('status', '未知')}\n物流：{o.get('tracking', '无')}"
        return f"❌ 数据库里没找到单号：{order_str}"
    except Exception as e:
        return f"⚠️ 数据库访问崩溃: {str(e)}"


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    user_text = data["message"].get("text", "")

    # 1. 立即回传一个确认收到，排查是否卡在 AI 阶段
    print(f"DEBUG: Received {user_text}")

    try:
        tools = [
            {"type": "function", "function": {"name": "get_order",
                                              "parameters": {"type": "object", "properties": {"id": {"type": "string"}},
                                                             "required": ["id"]}}},
            {"type": "function", "function": {"name": "search_item",
                                              "parameters": {"type": "object", "properties": {"q": {"type": "string"}},
                                                             "required": ["q"]}}}
        ]

        response = client.chat.completions.create(
            model="grok-beta",
            messages=[{"role": "system", "content": "你是客服。查单用 get_order，搜货用 search_item。"},
                      {"role": "user", "content": user_text}],
            tools=tools
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                if call.function.name == "get_order":
                    # 关键修复：直接发送数据库结果
                    send_debug_msg(chat_id, db_get_order(args.get("id")))
                elif call.function.name == "search_item":
                    res = supabase.table("products").select("*").ilike("name", f"%{args.get('q')}%").execute()
                    if res.data:
                        item = res.data[0]
                        send_debug_msg(chat_id, f"*{item['name']}*", item.get('img'), item.get('buy_url'))
                    else:
                        send_debug_msg(chat_id, "没搜到这个宝贝。")
        else:
            send_debug_msg(chat_id, msg.content)

    except Exception as e:
        send_debug_msg(chat_id, f"❌ 系统逻辑崩溃: {str(e)}")

    return "ok", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))