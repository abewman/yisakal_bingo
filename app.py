import os
import random
import time
from flask import Flask, render_template_string, request, jsonify
import telebot
import sqlite3

app = Flask(__name__)

BOT_TOKEN = "9297828542:AAHR5y2gCXlffi2CcX6b2la4dcEBEy6UJCE"
bot = telebot.TeleBot(BOT_TOKEN)

# የእርስዎ የሬንደር ሊንክ
RENDER_URL = "https://yisakal-bingo-10.onrender.com"

DB_NAME = "yisakal_bingo.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            wallet REAL DEFAULT 1000.0,
            bonus REAL DEFAULT 0.0
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

# Telegram Webhook Endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403

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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = telebot.types.InlineKeyboardMarkup()
    web_app = telebot.types.WebAppInfo(url=RENDER_URL)
    markup.add(telebot.types.InlineKeyboardButton("🎮 ይሳቃል ቢንጎ ይጫወቱ", web_app=web_app))
    bot.reply_to(message, "🎉 ወደ **ይሳቃል ቢንጎ** እንኳን ደህና መጡ!\n\nካርቴላዎችን በመምረጥ በዕድልዎ ይወዳደሩ እና ሽልማት ይውሰዱ!", reply_markup=markup)

# Webhook አውቶማቲክ ማስተካከያ
try:
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{RENDER_URL}/webhook")
except Exception as e:
    print(f"Webhook setup error: {e}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
