from flask import Flask, request, jsonify
import os
import requests
import time
import random
import sqlite3

app = Flask(__name__)

BOT_TOKEN = "8708901586:AAFYNhENBj5dJ4J1MRyikHm-73-FGCVlRqQ"
ADMIN_CHAT_ID = "8416118350"
WEBAPP_URL = "https://yisakal-bingo-10.onrender.com"
DB_NAME = "yisakal_bingo.db"

# ዳታቤዝ እና ቴብሎች ማዘጋጀት (Database Initialization)
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # ተጠቃሚዎችን የምንመዘግብበት ቴብል
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            wallet REAL,
            bonus REAL,
            phone TEXT
        )
    ''')
    # የትራንዛክሽን ታሪክ የምንመዘግብበት ቴብል (Transaction History Table)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            type TEXT,
            amount REAL,
            details TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # አብነት (Admin) ተጠቃሚ ካለ መመዝገብ ወይም ማረጋገጥ
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, wallet, bonus, phone)
        VALUES (?, ?, ?, ?, ?)
    ''', ("8416118350", "አብነት", 6000.0, 0, "+2519********"))
    conn.commit()
    conn.close()

init_db()

def get_user_from_db(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT username, wallet, bonus, phone FROM users WHERE user_id = ?', (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"username": row[0], "wallet": row[1], "bonus": row[2], "phone": row[3]}
    return None

def save_user_to_db(user_id, username, wallet=0.0, bonus=0.0, phone="የግል"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, wallet, bonus, phone)
        VALUES (?, ?, ?, ?, ?)
    ''', (str(user_id), username, wallet, bonus, phone))
    conn.commit()
    conn.close()

def update_user_wallet_in_db(user_id, new_wallet):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET wallet = ? WHERE user_id = ?', (new_wallet, str(user_id)))
    conn.commit()
    conn.close()

def add_transaction(user_id, tx_type, amount, details):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (user_id, type, amount, details)
        VALUES (?, ?, ?, ?)
    ''', (str(user_id), tx_type, amount, details))
    conn.commit()
    conn.close()

user_states = {}

game_state = {
    "booked": {},          # {cartela_num: user_id}
    "user_cartelas": {},   # {user_id: [cartela1, cartela2, ...]}
    "game_status": "waiting", # waiting, countdown, live, finished
    "countdown_end": 0,
    "called_balls": [],
    "current_ball": "--",
    "winner_id": None,
    "winner_name": None,
    "winning_cartela": None,
    "prize": 0.0,
    "last_call_time": 0
}

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
            
            user = get_user_from_db(target_user_id)
            if user:
                new_wallet = user["wallet"] + amount
                update_user_wallet_in_db(target_user_id, new_wallet)
            else:
                save_user_to_db(target_user_id, "Player", wallet=amount)
            
            add_transaction(target_user_id, "DEPOSIT", amount, "በአድሚን የጸደቀ ዲፖዚት")
            
            answer_callback(query['id'], "✅ ክፍያው ተረጋግጧል!")
            send_telegram_message(chat_id, f"✅ ጥያቄው ጸድቋል! {amount} ብር ተጨምሯል።")
            send_telegram_message(target_user_id, f"🎉 ክፍያዎ ተረጋግጦ ዎሌትዎ ላይ **{amount} ብር** ተጨምሯል።")

        elif callback_data.startswith("wdapp_"):
            parts = callback_data.split("_")
            target_user_id = parts[1]
            amount = float(parts[2])
            
            add_transaction(target_user_id, "WITHDRAW", amount, "በአድሚን የተለቀቀ ገንዘብ")
            
            answer_callback(query['id'], "✅ የገንዘብ ማውጣት ተረጋግጧል!")
            send_telegram_message(chat_id, f"✅ የ {amount} ብር ማውጣት ጥያቄ በአድሚኑ ጸድቆ ተልኳል።")
            send_telegram_message(target_user_id, f"💸 የጠየቁት **{amount} ብር** ወደ ቴሌብር/ባንክ አካውንትዎ ተልኳል!")
            
        return jsonify({"status": "success"})

    if 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        user_id = str(message['from']['id'])
        username = message['from'].get('first_name', 'ተጫዋች')
        
        if not get_user_from_db(user_id):
            save_user_to_db(user_id, username, wallet=0.0, bonus=0, phone="የግል")

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
            user = get_user_from_db(user_id)
            wallet_amt = user["wallet"] if user else 0.0
            send_telegram_message(chat_id, f"💰 የዎሌት ሒሳብዎ: **{wallet_amt} ብር** ነው።")
        elif 'መሙላት' in text or 'Deposit' in text:
            user_states[user_id] = {"action": "waiting_for_amount"}
            send_telegram_message(chat_id, "💳 ከ 50 እስከ 3000 ብር ድረስ ማስገባት የሚፈልጉትን የብር መጠን ቁጥር ብቻ ይጻፉልን (ለምሳሌ: 500)።")
        elif 'ማውጣት' in text or 'Withdraw' in text:
            user_states[user_id] = {"action": "waiting_for_withdraw"}
            send_telegram_message(chat_id, "💸 ለማውጣት የሚፈልጉትን **የብር መጠን እና የቴሌብር/ባንክ አካውንት ቁጥር** በአንድ ላይ ይጻፉ (ለምሳሌ: `200 0911223344`)።")
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
        elif user_states.get(user_id, {}).get("action") == "waiting_for_withdraw":
            try:
                user = get_user_from_db(user_id)
                current_wallet = user["wallet"] if user else 0.0
                parts = text.split(maxsplit=1)
                amount = float(parts[0])
                account_details = parts[1] if len(parts) > 1 else "አካውንት አልተገለጸም"

                if amount > current_wallet:
                    send_telegram_message(chat_id, f"⚠️ በዎሌትዎ ውስጥ ያለው በቂ አይደለም! (ቀሪ ሒሳብዎ: {current_wallet} ብር)")
                elif amount < 50:
                    send_telegram_message(chat_id, "⚠️ ዝቅተኛው የማውጫ መጠን 50 ብር ነው።")
                else:
                    new_wallet = current_wallet - amount
                    update_user_wallet_in_db(user_id, new_wallet)
                    forward_withdraw_to_admin(user_id, username, amount, account_details)
                    send_telegram_message(chat_id, f"✅ የ {amount} ብር የማውጣት ጥያቄዎ በአግባቡ ተልኳል! አድሚኑ ገንዘቡን ወደ ቴሌብር/ባንክ ቁጥርዎ ሲልክልዎ ማሳወቂያ ይደርስዎታል።")
                    user_states[user_id] = None
            except (ValueError, IndexError):
                send_telegram_message(chat_id, "⚠️ እባክዎ በትክክል ይጻፉ (ለምሳሌ: `200 0911223344`)።")
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

def forward_withdraw_to_admin(user_id, username, amount, details):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
        "chat_id": ADMIN_CHAT_ID,
        "text": f"💸 **አዲስ የገንዘብ ማውጣት (Withdraw) ጥያቄ!**\n👤 ስም: {username}\n🆔 ID: `{user_id}`\n💰 መጠን: **{amount} ብር**\n📱 አካውንት/ቁጥር: `{details}`",
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": [[{"text": f"✅ ገንዘብ ልኬ አረጋግጥ", "callback_data": f"wdapp_{user_id}_{amount}"}]]}
    })

def answer_callback(callback_query_id, text):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": callback_query_id, "text": text, "show_alert": True})

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    user = get_user_from_db(user_id)
    if not user:
        save_user_to_db(user_id, "አብነት", wallet=6000.0, bonus=0, phone="የግል")
        user = get_user_from_db(user_id)
    return jsonify({"success": True, **user})

@app.route('/api/transactions/<user_id>', methods=['GET'])
def get_transactions(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT type, amount, details, timestamp FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10', (str(user_id),))
    rows = cursor.fetchall()
    conn.close()
    
    txs = [{"type": r[0], "amount": r[1], "details": r[2], "timestamp": r[3]} for r in rows]
    return jsonify({"success": True, "transactions": txs})

@app.route('/api/booked', methods=['GET'])
def get_booked():
    now = time.time()
    total_booked_count = len(game_state["booked"])
    prize = total_booked_count * 8.0
    game_state["prize"] = prize

    if game_state["game_status"] == "waiting" and total_booked_count >= 2:
        game_state["game_status"] = "countdown"
        game_state["countdown_end"] = now + 25
    elif game_state["game_status"] == "countdown":
        if now >= game_state["countdown_end"]:
            game_state["game_status"] = "live"
            game_state["called_balls"] = []
            game_state["current_ball"] = "--"
            game_state["last_call_time"] = now
    elif game_state["game_status"] == "live":
        if now - game_state["last_call_time"] >= 2.5:
            game_state["last_call_time"] = now
            available = [i for i in range(1, 76) if i not in game_state["called_balls"]]
            if available:
                ball = random.choice(available)
                game_state["called_balls"].append(ball)
                game_state["current_ball"] = ball

    return jsonify({
        "booked": [int(k) for k in game_state["booked"].keys()],
        "active_players": total_booked_count,
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

    if game_state["game_status"] == "live":
        return jsonify({"success": False, "message": "⚠️ ጨዋታው ተጀምሯል! እባክዎ ቀጣዩን ዙር ይጠብቁ።"})

    if str(cartela_num) in [str(k) for k in game_state["booked"].keys()]:
        return jsonify({"success": False, "message": f"⚠️ ካርቴላ ቁጥር #{cartela_num} ተይዟል!"})

    user = get_user_from_db(user_id)
    if not user:
        save_user_to_db(user_id, "አብነት", wallet=6000.0, bonus=0, phone="የግል")
        user = get_user_from_db(user_id)

    if user["wallet"] < 10:
        return jsonify({"success": False, "message": "⚠️ በቂ ገንዘብ የለዎትም! ዎሌትዎን ይሙሉን።"})

    new_wallet = user["wallet"] - 10
    update_user_wallet_in_db(user_id, new_wallet)
    add_transaction(user_id, "CARTELA_BUY", 10, f"ካርቴላ ቁጥር #{cartela_num} ግዢ")

    game_state["booked"][str(cartela_num)] = user_id
    
    if user_id not in game_state["user_cartelas"]:
        game_state["user_cartelas"][user_id] = []
    if cartela_num not in game_state["user_cartelas"][user_id]:
        game_state["user_cartelas"][user_id].append(cartela_num)

    now = time.time()
    total_booked = len(game_state["booked"])
    if game_state["game_status"] == "waiting" and total_booked >= 2:
        game_state["game_status"] = "countdown"
        game_state["countdown_end"] = now + 25

    return jsonify({"success": True, "message": f"ካርቴላ #${cartela_num} ተይዟል!"})

@app.route('/api/win', methods=['POST'])
def declare_win():
    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = data.get('cartela_num')
    prize = game_state["prize"]

    user = get_user_from_db(user_id)
    if user:
        new_wallet = user["wallet"] + prize
        update_user_wallet_in_db(user_id, new_wallet)
        winner_name = user["username"]
        add_transaction(user_id, "WIN_PRIZE", prize, f"ካርቴላ #{cartela_num} የቢንጎ ሽልማት")
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
    game_state["prize"] = 0.0
    game_state["last_call_time"] = 0
    return jsonify({"success": True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
