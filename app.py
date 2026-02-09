import os
import json
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- 1. 配置加载 ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROK_KEY = os.environ.get("GROK_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=GROK_KEY, base_url="https://api.x.ai/v1")


# --- 2. 强力发送函数 ---
def send_final(chat_id, text, photo=None, url=None):
    markup = {"inline_keyboard": [[{"text": "🛒 Buy Now", "url": url}]]} if url else None
    if photo and photo.startswith("http"):
        api = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo, "caption": text, "parse_mode": "Markdown",
                   "reply_markup": markup}
    else:
        api = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": markup}
    requests.post(api, json=payload, timeout=10)


# --- 3. 暴力查单逻辑 (直接查询，不走 AI) ---
def direct_check_order(order_id):
    oid = str(order_id).strip()
    try:
        # 同时尝试 orders 和 order 表
        for table in ["orders", "order"]:
            res = supabase.table(table).select("*").eq("order_id", oid).execute()
            if res.data:
                o = res.data[0]
                return f"✅ **订单查询成功**\n\n单号：`{oid}`\n状态：{o.get('status', '处理中')}\n物流：{o.get('tracking', '无信息')}"
        return f"❌ 数据库中未找到单号: `{oid}`"
    except Exception as e:
        return f"⚠️ 数据库访问错误: {str(e)}"


# --- 4. 路由处理 ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    user_text = data["message"].get("text", "").strip()

    print(f"DEBUG: Received {user_text}")

    # --- 核心修复：直接拦截数字或订单号 ---
    if user_text.isdigit() or (len(user_text) > 3 and any(c in user_text for c in ["查", "订单", "order"])):
        # 提取数字
        potential_id = ''.join(filter(str.isdigit, user_text))
        if potential_id:
            send_final(chat_id, direct_check_order(potential_id))
            return "ok", 200

    # --- 非查单请求，走 AI 搜货 ---
    try:
        tools = [
            {"type": "function", "function": {"name": "search_item",
                                              "parameters": {"type": "object", "properties": {"q": {"type": "string"}},
                                                             "required": ["q"]}}}
        ]

        # 增加超时保护，防止 AI 导致不回复
        response = client.chat.completions.create(
            model="grok-beta",  # 如果报错，请改为你的 API 支持的模型名
            messages=[{"role": "system", "content": "你是新加坡艺术导购。搜东西用 search_item。"},
                      {"role": "user", "content": user_text}],
            tools=tools,
            timeout=15
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            for call in msg.tool_calls:
                q = json.loads(call.function.arguments).get("q")
                res = supabase.table("products").select("*").ilike("name", f"%{q}%").execute()
                if res.data:
                    item = res.data[0]
                    send_final(chat_id, f"*{item['name']}*\n{item.get('desc', '')}", item.get('img'),
                               item.get('buy_url'))
                else:
                    send_final(chat_id, "没搜到这个宝贝哦。")
        else:
            send_final(chat_id, msg.content)

    except Exception as e:
        print(f"AI ERROR: {e}")
        send_final(chat_id, "客服忙，请直接输入订单号查询或稍后再试。")

    return "ok", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))