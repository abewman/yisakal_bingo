from flask import Flask, request, jsonify
import os
import requests
import time
import threading
import random

app = Flask(__name__)

BOT_TOKEN = "8708901586:AAFYNhENBj5dJ4J1MRyikHm-73-FGCVlRqQ"
ADMIN_CHAT_ID = "8416118350"

# አዲሱ የዌብ አፕ ሊንክ በቦቱ ቁልፍ ላይ እንዲሰራ ተደርጓል
WEBAPP_URL = "https://yisakal-bingo-10.onrender.com"

users_db = {
    "8416118350": {"username": "አብነት", "wallet": 6000.0, "bonus": 0, "phone": "+2519********"}
}

user_states = {}

game_state = {
    "booked": {},
    "user_cartelas": {},
    "game_status": "waiting",
    "countdown_end": 0,
    "called_balls": [],
    "current_ball": "--",
    "winner_id": None,
    "winner_name": None,
    "winning_cartela": None,
    "prize": 50.0
}

def background_game_loop():
    while True:
        time.sleep(1)
        now = time.time()
        
        if game_state["game_status"] == "countdown":
            if now >= game_state["countdown_end"]:
                game_state["game_status"] = "live"
                game_state["called_balls"] = []
                game_state["current_ball"] = "--"
        
        elif game_state["game_status"] == "live":
            if not hasattr(background_game_loop, "last_call"):
                background_game_loop.last_call = 0
            
            if now - background_game_loop.last_call >= 2.5:
                background_game_loop.last_call = now
                available = [i for i in range(1, 76) if i not in game_state["called_balls"]]
                if available:
                    ball = random.choice(available)
                    game_state["called_balls"].append(ball)
                    game_state["current_ball"] = ball

threading.Thread(target=background_game_loop, daemon=True).start()

@app.route('/')
def home():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "ይሳቃል ቢንጎ ሰርቨር በትክክል እየሰራ ነው!"

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "ok"})

    if 'callback_query' in data:
        query = data['callback_query']
        chat_id = query['message']['chat']['id']
        callback_data = query['data']
        
        if callback_data.startswith("app_"):
            parts = callback_data.split("_")
            target_user_id = parts[1]
            amount = float(parts[2])
            
            if target_user_id in users_db:
                users_db[target_user_id]["wallet"] += amount
            else:
                users_db[target_user_id] = {"username": "Player", "wallet": amount, "bonus": 0, "phone": "የግል"}
            
            answer_callback(query['id'], "✅ ክፍያው ተረጋግጧል!")
            send_telegram_message(chat_id, f"✅ ጥያቄው ጸድቋል! {amount} ብር ተጨምሯል።")
            send_telegram_message(target_user_id, f"🎉 ክፍያዎ ተረጋግጦ ዎሌትዎ ላይ **{amount} ብር** ተጨምሯል።")
            
        return jsonify({"status": "success"})

    if 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        user_id = str(message['from']['id'])
        
        if user_id not in users_db:
            users_db[user_id] = {"username": message['from'].get('first_name', 'Player'), "wallet": 0.0, "bonus": 0, "phone": "የግል"}

        if 'photo' in message:
            if user_states.get(user_id, {}).get("action") == "awaiting_screenshot":
                amount = user_states[user_id]["amount"]
                photo_id = message['photo'][-1]['file_id']
                forward_deposit_to_admin(user_id, amount, photo_id)
                send_telegram_message(chat_id, "✅ ስክሪንሾትዎ ተቀብሏል! አድሚኑ ሲያረጋግጠው ዎሌትዎ ላይ ይጨመራል።")
                user_states[user_id] = None
            else:
                send_telegram_message(chat_id, "⚠️ እባክዎ መጀመሪያ 'ሒሳብ መሙላት' የሚለውን ይጫኑ።")
            return jsonify({"status": "success"})

        text = message.get('text', '')

        if text == '/start' or 'ጨዋታ' in text or 'Play' in text:
            send_webapp_button(chat_id, "🎮 ወደ ይሳቃል ቢንጎ እንኳን ደህና መጡ! ጨዋታውን ለመጀመር ከታች ያለውን ቁልፍ ይጫኑ።")
        elif 'ዎሌት' in text or 'Balance' in text:
            wallet_amt = users_db[user_id]["wallet"]
            send_telegram_message(chat_id, f"💰 የዎሌት ሒሳብዎ: **{wallet_amt} ብር** ነው።")
        elif 'መሙላት' in text or 'Deposit' in text:
            user_states[user_id] = {"action": "waiting_for_amount"}
            send_telegram_message(chat_id, "💳 ከ 50 እስከ 3000 ብር ድረስ ማስገባት የሚፈልጉትን የብር መጠን ቁጥር ብቻ ይጻፉልን (ለምሳሌ: 500)።")
        elif 'ማውጣት' in text or 'Withdraw' in text:
            send_telegram_message(chat_id, "💸 ገንዘብ ለማውጣት የሚፈልጉትን መጠን ይጻፉ።")
        elif user_states.get(user_id, {}).get("action") == "waiting_for_amount":
            try:
                amount = float(text)
                if 50 <= amount <= 3000:
                    user_states[user_id] = {"action": "awaiting_screenshot", "amount": amount}
                    bank_info = (
                        f"💳 **የገንዘብ ማስተላለፊያ አካውንቶች ({amount} ብር):**\n\n"
                        f"🏦 **CBE (የንግድ ባንክ):** `1000783589277` (Abinet Mifeta)\n"
                        f"📱 **Telebirr:** `0955358565` (Abinet)\n\n"
                        f"⚠️ ገንዘቡን ከላኩ በኋላ **ስክሪንሾት (Screenshot)** ፎቶ በዚህ ቦት ላይ ይላኩ!"
                    )
                    send_telegram_message(chat_id, bank_info)
                else:
                    send_telegram_message(chat_id, "⚠️ እባክዎ ከ **50 እስከ 3000 ብር** መካከል ትክክለኛ መጠን ያስገቡ።")
            except ValueError:
                send_telegram_message(chat_id, "⚠️ ትክክለኛ የቁጥር መጠን ብቻ ይላኩ።")
        else:
            send_webapp_button(chat_id, "🎮 ወደ ይሳቃል ቢንጎ እንኳን ደህና መጡ! ጨዋታውን ለመጀመር ከታች ያለውን ቁልፍ ይጫኑ።")

    return jsonify({"status": "success"})

def send_telegram_message(chat_id, text):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

def send_webapp_button(chat_id, text):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
        "chat_id": chat_id, "text": text,
        "reply_markup": {"inline_keyboard": [[{"text": "🎮 ይሳቃል ቢንጎ (Mini App) ክፈት", "web_app": {"url": WEBAPP_URL}}]]}
    })

def forward_deposit_to_admin(user_id, amount, photo_id):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
        "chat_id": ADMIN_CHAT_ID, "photo": photo_id,
        "caption": f"🔔 **አዲስ የዲፖዚት ጥያቄ!**\n👤 ID: `{user_id}`\n💰 መጠን: **{amount} ብር**",
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": [[{"text": f"✅ አጽድቅ (+{amount} ብር)", "callback_data": f"app_{user_id}_{amount}"}]]}
    })

def answer_callback(callback_query_id, text):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": callback_query_id, "text": text, "show_alert": True})

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    user = users_db.get(user_id, {"username": "Player", "wallet": 0.0, "bonus": 0, "phone": "የግል"})
    return jsonify({"success": True, **user})

@app.route('/api/booked', methods=['GET'])
def get_booked():
    total_booked_count = len(game_state["booked"])
    total_pool = total_booked_count * 10
    prize = max(50.0, total_pool * 0.8)
    game_state["prize"] = prize

    return jsonify({
        "booked": [int(k) for k in game_state["booked"].keys()],
        "active_players": max(1, len(set(game_state["booked"].values()))),
        "game_status": game_state["game_status"],
        "countdown_end": game_state["countdown_end"],
        "prize": prize,
        "called_balls": game_state["called_balls"],
        "current_ball": game_state["current_ball"],
        "winner_id": game_state["winner_id"],
        "winner_name": game_state["winner_name"],
        "winning_cartela": game_state["winning_cartela"]
    })

@app.route('/api/my_cartelas/<user_id>', methods=['GET'])
def get_my_cartelas(user_id):
    cartelas = game_state["user_cartelas"].get(user_id, [])
    return jsonify({"success": True, "cartelas": cartelas})

@app.route('/api/book', methods=['POST'])
def book_cartela():
    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = int(data.get('cartela_num'))

    if str(cartela_num) in [str(k) for k in game_state["booked"].keys()]:
        return jsonify({"success": False, "message": f"⚠️ ካርቴላ ቁጥር #{cartela_num} ተይዟል!"})

    if user_id not in users_db:
        users_db[user_id] = {"username": "Player", "wallet": 0.0, "bonus": 0, "phone": "የግል"}

    if users_db[user_id]["wallet"] < 10:
        return jsonify({"success": False, "message": "⚠️ በቂ ገንዘብ የለዎትም! ዎሌትዎን ይሙሉን።"})

    users_db[user_id]["wallet"] -= 10
    game_state["booked"][str(cartela_num)] = user_id
    
    if user_id not in game_state["user_cartelas"]:
        game_state["user_cartelas"][user_id] = []
    if cartela_num not in game_state["user_cartelas"][user_id]:
        game_state["user_cartelas"][user_id].append(cartela_num)

    if game_state["game_status"] == "waiting":
        game_state["game_status"] = "countdown"
        game_state["countdown_end"] = time.time() + 25

    return jsonify({"success": True, "message": f"ካርቴላ #{cartela_num} ተይዟል!"})

@app.route('/api/win', methods=['POST'])
def declare_win():
    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = data.get('cartela_num')
    prize = game_state["prize"]

    if user_id in users_db:
        users_db[user_id]["wallet"] += prize
        winner_name = users_db[user_id]["username"]
    else:
        winner_name = "ተጫዋች"

    game_state["game_status"] = "finished"
    game_state["winner_id"] = user_id
    game_state["winner_name"] = winner_name
    game_state["winning_cartela"] = cartela_num

    return jsonify({"success": True, "prize": prize})

@app.route('/api/reset_game', methods=['POST'])
def reset_game():
    game_state["booked"] = {}
    game_state["user_cartelas"] = {}
    game_state["game_status"] = "waiting"
    game_state["countdown_end"] = 0
    game_state["called_balls"] = []
    game_state["current_ball"] = "--"
    game_state["winner_id"] = None
    game_state["winner_name"] = None
    game_state["winning_cartela"] = None
    game_state["prize"] = 50.0
    return jsonify({"success": True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
