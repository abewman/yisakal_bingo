import os
import random
import time
from flask import Flask, render_template_string, request, jsonify
import telebot
import sqlite3

app = Flask(__name__)

BOT_TOKEN = "9021689838:AAGEOozXITFdr8WJNHwa6HySfS63FIgJARo"
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# የአድሚን (የእርስዎ) የቴሌግራም መለያ ቁጥር
ADMIN_CHAT_ID = "8416118350"

RENDER_URL = "https://yisakal-bingo-10.onrender.com"
DB_NAME = "yisakal_bingo.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            phone_number TEXT,
            wallet REAL DEFAULT 1000.0,
            bonus REAL DEFAULT 0.0,
            state TEXT DEFAULT 'IDLE',
            temp_amount REAL DEFAULT 0
        )
    ''')
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS booked_cartelas (
            cartela_num INTEGER PRIMARY KEY,
            user_id TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

game_status = "waiting"
countdown_end = 0
live_start_time = 0
called_balls = []
winner_info = {"name": "", "cartela": 0, "prize": 0}

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        return render_template_string(html_content)
    except Exception as e:
        return f"Error loading index.html: {str(e)}"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Invalid', 403

@app.route('/api/user/<user_id>')
def get_user(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (user_id, username, wallet, bonus) VALUES (?, ?, ?, ?)", 
                     (user_id, f"Player_{user_id[-4:]}", 1000.0, 0.0))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return jsonify({
        "success": True,
        "user_id": user["user_id"],
        "username": user["username"],
        "wallet": user["wallet"],
        "bonus": user["bonus"]
    })

@app.route('/api/transactions/<user_id>')
def get_transactions(user_id):
    conn = get_db_connection()
    txs = conn.execute("SELECT type, amount, details, timestamp FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)).fetchall()
    conn.close()
    return jsonify({
        "success": True,
        "transactions": [dict(tx) for tx in txs]
    })

@app.route('/api/booked')
def get_booked():
    conn = get_db_connection()
    booked = conn.execute("SELECT cartela_num FROM booked_cartelas").fetchall()
    booked_list = [row["cartela_num"] for row in booked]
    active_players = conn.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM booked_cartelas").fetchone()["cnt"]
    conn.close()
    
    prize = len(booked_list) * 10 * 0.8
    
    return jsonify({
        "success": True,
        "booked": booked_list,
        "active_players": active_players,
        "prize": int(prize),
        "game_status": game_status,
        "countdown_end": countdown_end,
        "called_balls": called_balls,
        "winner_name": winner_info["name"],
        "winning_cartela": winner_info["cartela"]
    })

@app.route('/api/book', methods=['POST'])
def book_cartela():
    global game_status, countdown_end
    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = int(data.get('cartela_num'))
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user or user["wallet"] < 10:
        conn.close()
        return jsonify({"success": False, "message": "⚠️ በቂ የኪስ ቦርሳ ሒሳብ የለዎትም (10 ብር ያስፈልጋል)!"})
    
    existing = conn.execute("SELECT * FROM booked_cartelas WHERE cartela_num = ?", (cartela_num,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"success": False, "message": f"⚠️ ካርቴላ ቁጥር #{cartela_num} უკვე ተይዟል!"})
    
    conn.execute("UPDATE users SET wallet = wallet - 10 WHERE user_id = ?", (user_id,))
    conn.execute("INSERT INTO booked_cartelas (cartela_num, user_id) VALUES (?, ?)", (cartela_num, user_id))
    conn.execute("INSERT INTO transactions (user_id, type, amount, details) VALUES (?, ?, ?, ?)",
                 (user_id, "BUY_CARTELA", 10, f"ካርቴላ ቁጥር #{cartela_num} ግዢ"))
    conn.commit()
    conn.close()
    
    if game_status == "waiting":
        game_status = "countdown"
        countdown_end = time.time() + 10
        import threading
        threading.Thread(target=run_game_loop).start()
        
    return jsonify({"success": True, "message": "በተሳካ ሁኔታ ተይዟል!"})

@app.route('/api/my_cartelas/<user_id>')
def get_my_cartelas(user_id):
    conn = get_db_connection()
    carts = conn.execute("SELECT cartela_num FROM booked_cartelas WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return jsonify({"success": True, "cartelas": [c["cartela_num"] for c in carts]})

@app.route('/api/win', methods=['POST'])
def declare_win():
    global game_status
    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = int(data.get('cartela_num'))
    prize = float(data.get('prize', 0))
    
    conn = get_db_connection()
    user = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
    username = user["username"] if user else "አብነት"
    
    global winner_info
    winner_info = {"name": username, "cartela": cartela_num, "prize": prize}
    game_status = "finished"
    
    conn.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (prize, user_id))
    conn.execute("INSERT INTO transactions (user_id, type, amount, details) VALUES (?, ?, ?, ?)",
                 (user_id, "WIN_PRIZE", prize, f"ካርቴላ #{cartela_num} ማሸነፊያ ደርሽ"))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True})

@app.route('/api/reset_game', methods=['POST'])
def reset_game():
    global game_status, called_balls, winner_info
    game_status = "waiting"
    called_balls = []
    winner_info = {"name": "", "cartela": 0, "prize": 0}
    
    conn = get_db_connection()
    conn.execute("DELETE FROM booked_cartelas")
    conn.commit()
    conn.close()
    return jsonify({"success": True})

def run_game_loop():
    global game_status, countdown_end, live_start_time, called_balls
    while game_status == "countdown":
        if time.time() >= countdown_end:
            game_status = "live"
            live_start_time = time.time()
            break
        time.sleep(1)
        
    all_numbers = list(range(1, 76))
    random.shuffle(all_numbers)
    
    idx = 0
    while game_status == "live" and idx < len(all_numbers):
        called_balls.append(all_numbers[idx])
        idx += 1
        time.sleep(3)

# 1. /start - ምዝገባ እና ስልክ ቁጥር መጠየቅ
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (user_id, username, wallet, bonus, state) VALUES (?, ?, ?, ?, ?)", 
                     (user_id, message.from_user.username or f"Player_{user_id[-4:]}", 1000.0, 0.0, 'IDLE'))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()

    if not user["phone_number"]:
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn_phone = telebot.types.KeyboardButton("📱 ስልክ ቁጥር አጋራ (Share Contact)", request_contact=True)
        markup.add(btn_phone)
        
        welcome_text = (
            "🎉 ወደ **ይሳቃል ቢንጎ** በደህና መጡ!\n\n"
            "ለመመዝገብ እና ጨዋታውን ለመጀመር ከታች ያለውን የስልክ ቁጥር በተን ይጫኑ።"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=markup)
    else:
        show_main_menu(message.chat.id, user["wallet"])

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = str(message.chat.id)
    if message.contact is not None:
        phone_number = message.contact.phone_number
        username = message.from_user.username or f"Player_{user_id[-4:]}"
        
        conn = get_db_connection()
        conn.execute("UPDATE users SET phone_number = ?, username = ? WHERE user_id = ?", (phone_number, username, user_id))
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        conn.commit()
        wallet_balance = user["wallet"]
        conn.close()

        remove_markup = telebot.types.ReplyKeyboardRemove()
        bot.send_message(message.chat.id, "✅ ምዝገባዎ በሳካ ሁኔታ ተጠናቋል!", reply_markup=remove_markup)
        show_main_menu(message.chat.id, wallet_balance)

def show_main_menu(chat_id, wallet_balance):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_play = telebot.types.KeyboardButton("🎮 ይሳቃል ቢንጎ ይጫወቱ")
    btn_deposit = telebot.types.KeyboardButton("📥 ገንዘብ ገቢ ማድረግ")
    btn_withdraw = telebot.types.KeyboardButton("📤 ገንዘብ ማውጣት")
    btn_balance = telebot.types.KeyboardButton("💰 የኪስ ቦርሳ ሒሳብ")
    markup.add(btn_play, btn_deposit, btn_withdraw, btn_balance)

    menu_text = (
        f"💰 ዋሌት (ሂሳብ): {wallet_balance} ብር\n\n"
        "እባክዎ ከታች ከሚገኙት አማራጮች የሚፈልጉትን ይምረጡ፡"
    )
    bot.send_message(chat_id, menu_text, reply_markup=markup)

# የጽሁፍ መልዕክቶች እና የሜኑ ምርጫዎች አስተዳደር
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = str(message.chat.id)
    text = message.text.strip()
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    if not user:
        conn.close()
        bot.send_message(message.chat.id, "እባክዎ መጀመሪያ /start በመጫን ይመዝገቡ!")
        return

    state = user["state"]

    # 1. ገንዘብ ገቢ ማድረግ Flow
    if text == "📥 ገንዘብ ገቢ ማድረግ":
        conn.execute("UPDATE users SET state = 'WAITING_DEPOSIT_AMOUNT' WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, "💰 ከ **50 እስከ 3000 ብር** ድረስ ገቢ ማድረግ የሚፈልጉትን የብር መጠን በቁጥር ይጻፉልን:")
        return

    elif state == 'WAITING_DEPOSIT_AMOUNT':
        try:
            amount = float(text)
            if 50 <= amount <= 3000:
                conn.execute("UPDATE users SET state = 'WAITING_DEPOSIT_PROOF', temp_amount = ? WHERE user_id = ?", (amount, user_id))
                conn.commit()
                conn.close()
                
                deposit_info_text = (
                    f"📥 **የገንዘብ ገቢ ማድረጊያ አካውንቶች** (የጠየቁት መጠን: {amount} ብር)\n\n"
                    "እባክዎ ከታች ባሉት አካውንቶች በመልቀቅ ክፍያውን ይፈጽሙ:\n\n"
                    "🔹 **ቴሌብር (Telebirr):** `0955358565`\n"
                    "ስም፡ Abinet mifeta\n\n"
                    "🔹 **ንግድ ባንክ (CBE Birr):** `1000783589277`\n"
                    "ስም፡ Abinet mifeta\n\n"
                    "⚠️ **ማስጠንቀቂያ:** ክፍያውን ከፈጸሙ በኋላ የክፍያውን **ስክሪንሾት (Photo)** ወይም የባንክ ማረጋገጫ **ሜሴጅ** እዚህ ላይ ይላኩ!"
                )
                bot.send_message(message.chat.id, deposit_info_text, parse_mode="Markdown")
            else:
                conn.close()
                bot.send_message(message.chat.id, "⚠️ እባክዎ ከ **50 እስከ 3000 ብር** መካከል ብቻ ትክክለኛ መጠን ይጻፉ!")
        except ValueError:
            conn.close()
            bot.send_message(message.chat.id, "⚠️ እባክዎ ትክክለኛ የቁጥር መጠን በሰላም ይጻፉ (ለምሳሌ: 500)!")
        return

    # 2. ገንዘብ ማውጣት Flow
    elif text == "📤 ገንዘብ ማውጣት":
        conn.execute("UPDATE users SET state = 'WAITING_WITHDRAW_AMOUNT' WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, "📤 ከ **100 እስከ 3000 ብር** ድረስ ማውጣት የሚፈልጉትን የብር መጠን በቁጥር ይጻፉልን:")
        return

    elif state == 'WAITING_WITHDRAW_AMOUNT':
        try:
            amount = float(text)
            if 100 <= amount <= 3000:
                if user["wallet"] < amount:
                    conn.close()
                    bot.send_message(message.chat.id, f"⚠️ በቂ የኪስ ቦርሳ ሒሳብ የለዎትም! (ያሎት: {user['wallet']} ብር)")
                    return
                
                conn.execute("UPDATE users SET state = 'WAITING_WITHDRAW_ACCOUNT', temp_amount = ? WHERE user_id = ?", (amount, user_id))
                conn.commit()
                conn.close()
                bot.send_message(message.chat.id, "🏦 እባክዎ ገንዘብ ገቢ እንዲደረግልዎ የሚፈልጉትን **የቴሌብር ወይም የንግድ ባንክ አካውንት ቁጥር እና ስም** ይላኩልን:")
            else:
                conn.close()
                bot.send_message(message.chat.id, "⚠️ እባክዎ ከ **100 እስከ 3000 ብር** መካከል ብቻ ትክክለኛ መጠን ይጻፉ!")
        except ValueError:
            conn.close()
            bot.send_message(message.chat.id, "⚠️ እባክዎ ትክክለኛ የቁጥር መጠን ይጻፉ!")
        return

    elif state == 'WAITING_WITHDRAW_ACCOUNT':
        amount = user["temp_amount"]
        phone = user["phone_number"] or "ተጠቃሚ"
        username = user["username"]
        
        conn.execute("UPDATE users SET state = 'IDLE', temp_amount = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, "✅ የገንዘብ ማውጣት ጥያቄዎ በአግባቡ ተልኳል! በአስተዳዳሪው ተረጋግጦ ይለቀቅልዎታል።")
        show_main_menu(message.chat.id, user["wallet"])
        
        # ጥያቄውን ለአድሚን መላክ
        admin_msg = (
            f"📤 **አዲስ የገንዘብ ማውጣት ጥያቄ!**\n\n"
            f"👤 ተጠቃሚ: @{username} (ID: `{user_id}`)\n"
            f"📞 ስልክ: {phone}\n"
            f"💵 የጠየቀው መጠን: {amount} ብር\n"
            f"🏦 የተላከው አካውንት ዝርዝር:\n{text}"
        )
        try:
            bot.send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Error sending to admin: {e}")
        return

    # 3. የኪስ ቦርሳ ሒሳብ ማረጋገጥ
    elif text == "💰 የኪስ ቦርሳ ሒሳብ":
        conn.close()
        bot.send_message(message.chat.id, f"💰 የእርስዎ የኪስ ቦርሳ ሒሳብ: **{user['wallet']} ብር** ነውር።", parse_mode="Markdown")
        return

    elif text == "🎮 ይሳቃል ቢንጎ ይጫወቱ":
        conn.close()
        markup = telebot.types.InlineKeyboardMarkup()
        web_app = telebot.types.WebAppInfo(url=RENDER_URL)
        markup.add(telebot.types.InlineKeyboardButton("🎮 ሚኒ አፕ ክፈት", web_app=web_app))
        bot.send_message(message.chat.id, "ለመጫወት ከታች ያለውን በተን ይጫኑ:", reply_markup=markup)
        return

    conn.close()
    bot.send_message(message.chat.id, "እባክዎ ከታች ካሉት የሜኑ አማራጮች አንዱን ይምረጡ!")

# ተጠቃሚው የክፍያ ማረጋገጫ ፎቶ ወይም ጽሁፍ ሲልክ (ለዲፖዚት)
@bot.message_handler(content_types=['photo', 'text'])
def handle_deposit_proof(message):
    user_id = str(message.chat.id)
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    if not user or user["state"] != 'WAITING_DEPOSIT_PROOF':
        conn.close()
        return

    amount = user["temp_amount"]
    username = user["username"]
    phone = user["phone_number"] or "N/A"
    
    conn.execute("UPDATE users SET state = 'IDLE', temp_amount = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    wallet_balance = user["wallet"]
    conn.close()

    bot.send_message(message.chat.id, "✅ የክፍያ ማረጋገጫዎ ለአስተዳዳሪው ተልኳል! በአስተዳዳሪው ሲረጋገጥ በኪስ ቦርሳዎ ላይ ይጨመራል።")
    show_main_menu(message.chat.id, wallet_balance)

    # ለአድሚን ማሳወቂያ መላክ
    admin_caption = (
        f"📥 **አዲስ የገንዘብ ገቢ ማድረጊያ ማረጋገጫ!**\n\n"
        f"👤 ተጠቃሚ: @{username} (ID: `{user_id}`)\n"
        f"📞 ስልክ: {phone}\n"
        f"💵 የጠየቀው መጠን: {amount} ብር\n\n"
        "እባክዎ ክፍያውን አረጋግጦ ተጠቃሚው ላይ ለመጨመር የባንክ አካውንትዎን ይፈትሹ!"
    )
    try:
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
            bot.send_photo(ADMIN_CHAT_ID, file_id, caption=admin_caption, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_CHAT_ID, f"{admin_caption}\n\nተጠቃሚው የላከው መልዕክት: {message.text}", parse_mode="Markdown")
    except Exception as e:
        print(f"Error sending proof to admin: {e}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
