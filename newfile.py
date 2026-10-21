from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# የቦት ቶከንዎ በትክክል ተሞልቷል
BOT_TOKEN = "8708901586:AAFYNhENBj5dJ4J1MRyikHm-73-FGCVlRqQ"

# ተጠቃሚዎችን እና የዎሌት መረጃዎችን መያዣ (የእርስዎን መለያ 6000 ብር ቀድሞ እንዲኖረው ተደርጓል)
users_db = {
    "1544276218": {"username": "አብነት", "wallet": 6000.0, "bonus": 0, "phone": "+2519********"}
}

game_state = {
    "booked": [],
    "active_players": 1,
    "game_status": "waiting",
    "winner_id": None
}

@app.route('/')
def home():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "ይሳቃል ቢንጎ ሰርቨር በትክክል እየሰራ ነው!"

# የቴሌግራም ዌብሁክ (Webhook) ለቦቱ ምላሽ መስጫ
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "ok"})

    if 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')
        user_id = str(message['from']['id'])
        
        if user_id not in users_db:
            users_db[user_id] = {"username": message['from'].get('first_name', 'Player'), "wallet": 6000.0, "bonus": 0, "phone": "የግል"}

        if text == '/start' or 'ጨዋታ ጅምር' in text:
            send_telegram_message(chat_id, "🎮 ወደ ይሳቃል ቢንጎ እንኳን ደህና መጡ! ከታች ያለውን ሚኒ አፕ በመክፈት መጫወት ይችላሉ።")
        elif 'ዎሌት' in text or 'Balance' in text:
            wallet_amt = users_db[user_id]["wallet"]
            send_telegram_message(chat_id, f"💰 የዎሌት ሂሳብዎ: **{wallet_amt} ብር** ነው።")
        else:
            send_telegram_message(chat_id, f"ሰላም! መልዕክትዎ ደርሶናል። ዎሌትዎን ለማየት 'ዎሌት' ይበሉ።")

    return jsonify({"status": "success"})

def send_telegram_message(chat_id, text):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending message: {e}")

# API Endpoints ለ Mini App (Frontend)
@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    user = users_db.get(user_id, {"username": "Player", "wallet": 6000.0, "bonus": 0, "phone": "የግል"})
    return jsonify({"success": True, **user})

@app.route('/api/booked', methods=['GET'])
def get_booked():
    return jsonify({
        "booked": game_state["booked"],
        "active_players": len(game_state["booked"]) if len(game_state["booked"]) > 0 else 1,
        "game_status": game_state["game_status"],
        "winner_id": game_state["winner_id"]
    })

@app.route('/api/book', methods=['POST'])
def book_cartela():
    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = int(data.get('cartela_num'))

    if cartela_num in game_state["booked"]:
        return jsonify({"success": False, "message": f"⚠️ ካርቴላ ቁጥር #{cartela_num} ተይዟል!"})

    if user_id not in users_db:
        users_db[user_id] = {"username": "Player", "wallet": 6000.0, "bonus": 0, "phone": "የግል"}

    if users_db[user_id]["wallet"] < 10:
        return jsonify({"success": False, "message": "⚠️ በቂ ገንዘብ የለዎትም!"})

    users_db[user_id]["wallet"] -= 10
    game_state["booked"].append(cartela_num)
    return jsonify({"success": True, "message": "ተሳክቷል!"})

@app.route('/api/win', methods=['POST'])
def declare_win():
    data = request.json
    user_id = str(data.get('user_id'))
    prize = float(data.get('prize', 50))
    if user_id in users_db:
        users_db[user_id]["wallet"] += prize
    game_state["game_status"] = "finished"
    game_state["winner_id"] = user_id
    return jsonify({"success": True})

@app.route('/api/reset_game', methods=['POST'])
def reset_game():
    game_state["booked"] = []
    game_state["game_status"] = "waiting"
    game_state["winner_id"] = None
    return jsonify({"success": True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
