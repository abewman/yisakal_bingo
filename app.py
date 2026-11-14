import os
import random
import time
from flask import Flask, render_template_string, request, jsonify
import telebot
import sqlite3

app = Flask(__name__)

BOT_TOKEN = "9021689838:AAGEOozXITFdr8WJNHwa6HySfS63FIgJARo"
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

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
            wallet REAL DEFAULT 0.0,
            bonus REAL DEFAULT 10.0,
            has_received_bonus INTEGER DEFAULT 0,
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
        CREATE TABLE IF NOT EXISTS game_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            cartela_num INTEGER,
            result TEXT,
            prize REAL,
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
    try:
        if request.headers.get('content-type') and 'application/json' in request.headers.get('content-type'):
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return '', 200
    except Exception as e:
        print(f"Webhook error: {e}")
    return '', 200

@app.route('/api/user/<user_id>')
def get_user(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (user_id, username, wallet, bonus, has_received_bonus) VALUES (?, ?, ?, ?, ?)", 
                     (user_id, f"Player_{user_id[-4:]}", 0.0, 10.0, 1))
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
    games = conn.execute("SELECT cartela_num, result, prize, timestamp FROM game_history WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
    conn.close()
    
    combined = []
    for tx in txs:
        combined.append({
            "type": tx["type"],
            "amount": tx["amount"],
            "details": f"{tx['details']} ({tx['timestamp']})"
        })
    for g in games:
        combined.append({
            "type": g["result"],
            "amount": g["prize"],
            "details": f"ካርቴላ #{g['cartela_num']} - {g['result']} ({g['timestamp']})"
        })

    return jsonify({
        "success": True,
        "transactions": combined
    })

@app.route('/api/booked')
def get_booked():
    conn = get_db_connection()
    booked = conn.execute("SELECT cartela_num FROM booked_cartelas").fetchall()
    booked_list = [row["cartela_num"] for row in booked]
    total_cartelas = len(booked_list)
    conn.close()
    
    prize = total_cartelas * 10 * 0.8
    
    return jsonify({
        "success": True,
        "booked": booked_list,
        "active_players": total_cartelas,
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
    
    # 📌 ማስተካከያ 2: ካርቴላ መግዛት የሚከለክለው ጨዋታው 'live' (ቁጥሮች መውጣት ሲጀምሩ) ብቻ ነው እንጂ ቆጠራው (countdown) ላይ ሳለ መግዛት ይቻላል
    if game_status == "live":
        return jsonify({"success": False, "message": "⚠️ ጨዋታው ተጀምሯል! እባክዎ ቀጣዩን ጨዋታ በትዕግስት ይጠብቁ።"})

    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = int(data.get('cartela_num'))
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"success": False, "message": "⚠️ ተጠቃሚው አልተገኘም!"})
    
    deduct_from = "wallet"
    cost = 10.0
    if user["bonus"] >= cost:
        deduct_from = "bonus"
    elif user["wallet"] < cost:
        conn.close()
        return jsonify({"success": False, "message": "⚠️ በቂ የኪስ ቦርሳ ወይም የቦነስ ሒሳብ የለዎትም (10 ብር ያስፈልጋል)!"})
    
    existing = conn.execute("SELECT * FROM booked_cartelas WHERE cartela_num = ?", (cartela_num,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"success": False, "message": f"⚠️ ካርቴላ ቁጥር #{cartela_num} უკვე ተይዟል!"})
    
    if deduct_from == "bonus":
        conn.execute("UPDATE users SET bonus = bonus - ? WHERE user_id = ?", (cost, user_id))
    else:
        conn.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (cost, user_id))
        
    conn.execute("INSERT INTO booked_cartelas (cartela_num, user_id) VALUES (?, ?)", (cartela_num, user_id))
    conn.execute("INSERT INTO transactions (user_id, type, amount, details) VALUES (?, ?, ?, ?)",
                 (user_id, "BUY_CARTELA", cost, f"ካርቴላ ቁጥር #{cartela_num} ግዢ"))
    conn.commit()
    
    total_booked = conn.execute("SELECT COUNT(*) as cnt FROM booked_cartelas").fetchone()["cnt"]
    conn.close()
    
    # ቢያንስ 2 ካርቴላ ሲያዝ የ25 ሰከንድ ቆጠራ ይጀምራል (አዲስ ከገባ ግን ቆጠራው እንዳይቋረጥ እንጠብቃለን)
    if game_status == "waiting" and total_booked >= 2:
        game_status = "countdown"
        countdown_end = time.time() + 25
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
    username = user["username"] if user else "ተጫዋች"
    
    global winner_info
    winner_info = {"name": username, "cartela": cartela_num, "prize": prize}
    game_status = "finished"
    
    conn.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (prize, user_id))
    conn.execute("INSERT INTO transactions (user_id, type, amount, details) VALUES (?, ?, ?, ?)",
                 (user_id, "WIN_PRIZE", prize, f"ካርቴላ #{cartela_num} ማሸነፊያ ደርሽ"))
    conn.execute("INSERT INTO game_history (user_id, cartela_num, result, prize) VALUES (?, ?, ?, ?)",
                 (user_id, cartela_num, "WIN", prize))
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
        conn = get_db_connection()
        total_booked = conn.execute("SELECT COUNT(*) as cnt FROM booked_cartelas").fetchone()["cnt"]
        conn.close()
        if total_booked < 2:
            game_status = "waiting"
            return

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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    # 📌 ማስተካከያ 1: ተጠቃሚው ቀድሞ ከተመዘገበ እንደገና ስልክ ቁጥር እንዲልክ አናስገድደውም፤ ዳታቤዝ ላይ ያለውን መረጃ ይዘን እንቀጥላለን
    if not user:
        conn.execute("INSERT INTO users (user_id, username, wallet, bonus, has_received_bonus, state) VALUES (?, ?, ?, ?, ?, ?)", 
                     (user_id, message.from_user.username or f"Player_{user_id[-4:]}", 0.0, 10.0, 1, 'IDLE'))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()

    if not user["phone_number"]:
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn_phone = telebot.types.KeyboardButton("📱 ስልክ ቁጥር አጋራ (Share Contact)", request_contact=True)
        markup.add(btn_phone)
        
        welcome_text = (
            "🎉 ወደ **ይሳቃል ቢንጎ** በደህና መጡ!\n\n"
            "ለመመዝገብ እና የ10 ብር ነፃ የማስሞከሪያ ቦነስ ለማግኘት ከታች ያለውን የስልክ ቁጥር በተን ይጫኑ።"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=markup)
    else:
        bot.send_message(message.chat.id, f"ደህና መጡ! ዳታዎ ተረጋግጧል።")
        show_main_menu(message.chat.id)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = str(message.chat.id)
    if message.contact is not None:
        phone_number = message.contact.phone_number
        username = message.from_user.username or f"Player_{user_id[-4:]}"
        
        conn = get_db_connection()
        conn.execute("UPDATE users SET phone_number = ?, username = ? WHERE user_id = ?", (phone_number, username, user_id))
        conn.commit()
        conn.close()

        remove_markup = telebot.types.ReplyKeyboardRemove()
        bot.send_message(message.chat.id, f"✅ ምዝገባዎ በሳካ ሁኔታ ተጠናቋል!\n🎁 የ10 ብር የማስሞከሪያ ቦነስ ተሰጥቶዎታል።", reply_markup=remove_markup)
        show_main_menu(message.chat.id)

def show_main_menu(chat_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_play = telebot.types.KeyboardButton("🎮 ይሳቃል ቢንጎ ይጫወቱ")
    btn_deposit = telebot.types.KeyboardButton("📥 ገንዘብ ገቢ ማድረግ")
    btn_withdraw = telebot.types.KeyboardButton("📤 ገንዘብ ማውጣት")
    btn_balance = telebot.types.KeyboardButton("💰 የኪስ ቦርሳ ሒሳብ")
    markup.add(btn_play, btn_deposit, btn_withdraw, btn_balance)

    menu_text = "እባክዎ ከታች ከሚገኙት አማራጮች የሚፈልጉትን ይምረጡ፡"
    bot.send_message(chat_id, menu_text, reply_markup=markup)

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
            bot.send_message(message.chat.id, "⚠️ እባክዎ ትክክለኛ የቁጥር መጠን ይጻፉ (ለምሳሌ: 500)!")
        return

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
        show_main_menu(message.chat.id)
        
        # 📌 ማስተካከያ 3: ለአድሚን የገንዘብ ማውጫ ጥያቄ ሲላክ "አጽድቅ" የሚል በተን እንዲኖረው ተደረገ
        admin_msg = (
            f"📤 **አዲስ የገንዘብ ማውጣት ጥያቄ!**\n\n"
            f"👤 ተጠቃሚ: @{username} (ID: `{user_id}`)\n"
            f"📞 ስልክ: {phone}\n"
            f"💵 የጠየቀው መጠን: {amount} ብር\n"
            f"🏦 የተላከው አካውንት ዝርዝር:\n{text}"
        )
        markup = telebot.types.InlineKeyboardMarkup()
        btn_approve = telebot.types.InlineKeyboardButton(f"✅ አጽድቅ (ለቀቅ {amount} ብር)", callback_data=f"withdraw_{user_id}_{amount}")
        markup.add(btn_approve)

        try:
            bot.send_message(ADMIN_CHAT_ID, admin_msg, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            print(f"Error sending to admin: {e}")
        return

    elif text == "💰 የኪስ ቦርሳ ሒሳብ":
        conn.close()
        bot.send_message(message.chat.id, f"💰 ዋሌት: **{user['wallet']} ብር** | 🎁 ቦነስ: **{user['bonus']} ብር**", parse_mode="Markdown")
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
    conn.close()

    bot.send_message(message.chat.id, "✅ የክፍያ ማረጋገጫዎ ለአስተዳዳሪው ተልኳል!\nበአስተዳዳሪው ሲረጋገጥ በኪስ ቦርሳዎ ላይ ይጨመራል።")
    show_main_menu(message.chat.id)

    admin_caption = (
        f"🔔 **አዲስ የዲፖዚት ጥያቄ!**\n"
        f"👤 ID: `{user_id}`\n"
        f"👤 ተጠቃሚ: @{username}\n"
        f"📞 ስልክ: {phone}\n"
        f"💵 መጠን: {amount} ብር"
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    btn_approve = telebot.types.InlineKeyboardButton(f"✅ አጽድቅ (+{amount} ብር)", callback_data=f"approve_{user_id}_{amount}")
    markup.add(btn_approve)

    try:
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
            bot.send_photo(ADMIN_CHAT_ID, file_id, caption=admin_caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_CHAT_ID, f"{admin_caption}\n\nተጠቃሚው የላከው ጽሁፍ: {message.text}", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error sending proof to admin: {e}")

# አድሚኑ የዲፖዚት ወይም የዊዝድሮዋል አዝራር ሲጫን
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('withdraw_'))
def handle_admin_actions(call):
    if str(call.from_user.id) != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "⚠️ ይህንን እርምጃ መውሰድ የሚችለው አድሚኑ ብቻ ነው!", show_alert=True)
        return
    
    try:
        data_parts = call.data.split('_')
        action_type = data_parts[0]
        target_user_id = data_parts[1]
        amount = float(data_parts[2])
        
        conn = get_db_connection()
        target_user = conn.execute("SELECT * FROM users WHERE user_id = ?", (target_user_id,)).fetchone()
        
        if not target_user:
            conn.close()
            bot.answer_callback_query(call.id, "⚠️ ተጠቃሚው በዳታቤዙ ውስጥ አልተገኘም!", show_alert=True)
            return
            
        if action_type == 'approve':
            # ዲፖዚት ማጽደቅ (ዋሌት ላይ መጨመር)
            conn.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (amount, target_user_id))
            conn.execute("INSERT INTO transactions (user_id, type, amount, details) VALUES (?, ?, ?, ?)",
                         (target_user_id, "DEPOSIT", amount, f"በአድሚን የጸደቀ ገቢ መጠን: {amount} ብር"))
            conn.commit()
            
            updated_user = conn.execute("SELECT wallet FROM users WHERE user_id = ?", (target_user_id,)).fetchone()
            new_balance = updated_user["wallet"]
            conn.close()
            
            original_caption = call.message.caption or call.message.text
            new_caption = f"{original_caption}\n\n✅ **ጸድቋል (+{amount} ብር ተጨምሯል)**"
            
            if call.message.content_type == 'photo':
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=new_caption, parse_mode="Markdown")
            else:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=new_caption, parse_mode="Markdown")
                
            bot.answer_callback_query(call.id, "✅ ክፍያው ተጸድቆ ተጠቃሚው ላይ ተጨምሯል!")
            bot.send_message(target_user_id, f"✅ **የዲፖዚት ጥያቄዎ ጸድቋል! {amount} ብር ተጨምሯል።**\n\n💰 አጠቃላይ ሒሳብዎ: **{new_balance} ብር** ሆኗል።", parse_mode="Markdown")

        elif action_type == 'withdraw':
            # ዊዝድሮዋል ማጽደቅ (ከዋሌት መቀነስ)
            if target_user["wallet"] < amount:
                bot.answer_callback_query(call.id, "⚠️ የተጠቃሚው ሒሳብ ከጠየቀው መጠን ያነሰ ነው!", show_alert=True)
                conn.close()
                return

            conn.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (amount, target_user_id))
            conn.execute("INSERT INTO transactions (user_id, type, amount, details) VALUES (?, ?, ?, ?)",
                         (target_user_id, "WITHDRAW", amount, f"የወጣ ገንዘብ መጠን: {amount} ብር"))
            conn.commit()
            
            updated_user = conn.execute("SELECT wallet FROM users WHERE user_id = ?", (target_user_id,)).fetchone()
            new_balance = updated_user["wallet"]
            conn.close()
            
            original_text = call.message.text or call.message.caption
            new_text = f"{original_text}\n\n✅ **የወጪ ጥያቄው ጸድቆ ተለቋል (-{amount} ብር)**"
            
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=new_text, parse_mode="Markdown")
            bot.answer_callback_query(call.id, "✅ የገንዘብ ማውጣት ጥያቄው ጸድቋል!")
            bot.send_message(target_user_id, f"✅ **የገንዘብ ማውጣት ጥያቄዎ ጸድቆ ተልኳል!**\n\n💰 የቀረው የኪስ ቦርሳ ሒሳብዎ: **{new_balance} ብር** ነው።", parse_mode="Markdown")

    except Exception as e:
        print(f"Error in admin action: {e}")
        bot.answer_callback_query(call.id, "⚠️ ስህተት ተፈጥሯል!", show_alert=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
