from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# የቦት ቶከንዎ
BOT_TOKEN = "8708901586:AAFYNhENBj5dJ4J1MRyikHm-73-FGCVlRqQ"

# የአድሚን ቴሌግራም ዩዘር ID (ስክሪንሾት እና የጥያቄ ማሳወቂያ የሚደርሰው ባለቤት)
ADMIN_CHAT_ID = "1544276218"

# ተጠቃሚዎችን እና ዎሌት መያዣ
users_db = {
    "1544276218": {"username": "አብነት", "wallet": 6000.0, "bonus": 0, "phone": "+2519********"}
}

# የተጠቃሚዎችን ጊዜያዊ ሁኔታ (State) መቆጣጠሪያ (ለምሳሌ ዲፖዚት ሲያደርጉ)
user_states = {}

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

# የቴሌግራም ዌብሁክ (Webhook)
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "ok"})

    # 1. አድሚኑ አጽድቅ (Approve) የሚለውን ቁልፍ ሲጫን (Callback Query)
    if 'callback_query' in data:
        query = data['callback_query']
        chat_id = query['message']['chat']['id']
        callback_data = query['data']
        
        if callback_data.startswith("app_"):
            parts = callback_data.split("_")
            target_user_id = parts[1]
            amount = float(parts[2])
            
            # ተጠቃሚው ላይ ገንዘብ መጨመር
            if target_user_id in users_db:
                users_db[target_user_id]["wallet"] += amount
            else:
                users_db[target_user_id] = {"username": "Player", "wallet": amount, "bonus": 0, "phone": "የግል"}
            
            # ለአድሚን ማሳወቂያ ማስተካከል
            answer_callback(query['id'], "✅ ክፍያው ተረጋግጦ ገንዘቡ ተጨምሯል!")
            send_telegram_message(chat_id, f"✅ ጥያቄው ጸድቋል! ለተጠቃሚው **{amount} ብር** ተጨምሯል።")
            
            # ለተጠቃሚው ማሳወቂያ መላክ
            send_telegram_message(target_user_id, f"🎉 እንኳን ደስ አለዎት! የላኩት የ {amount} ብር ክፍያ ተረጋግጦ ዎሌትዎ ላይ ተጨምሯል።")
            
        return jsonify({"status": "success"})

    # 2. የተለመዱ መልዕክቶች እና ፎቶዎች (Messages & Photos)
    if 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        user_id = str(message['from']['id'])
        
        if user_id not in users_db:
            users_db[user_id] = {"username": message['from'].get('first_name', 'Player'), "wallet": 0.0, "bonus": 0, "phone": "የግል"}

        # ሀ) ተጠቃሚው ስክሪንሾት (ፎቶ) ሲልክ
        if 'photo' in message:
            if user_states.get(user_id, {}).get("action") == "awaiting_screenshot":
                amount = user_states[user_id]["amount"]
                photo_id = message['photo'][-1]['file_id']
                
                # ፎቶውን እና የክፍያ ጥያቄውን ወደ አድሚን መላክ
                forward_deposit_to_admin(user_id, amount, photo_id)
                
                send_telegram_message(chat_id, "✅ ስክሪንሾትዎ በትክክል ተቀብሏል! አድሚኑ ሲገመግመው ዎሌትዎ ላይ ይጨመራል።")
                user_states[user_id] = None # ስቴቱን ማጽዳት
            else:
                send_telegram_message(chat_id, "⚠️ እባክዎ መጀመሪያ 'ሒሳብ መሙላት' የሚለውን በመጫን መጠኑን ይጥቀሱ።")
            return jsonify({"status": "success"})

        # ለ) የፅሁፍ መልዕክቶች ሲመጡ
        text = message.get('text', '')

        # ጨዋታ ጅምር
        if text == '/start' or 'ጨዋታ' in text or 'Play' in text:
            send_webapp_button(chat_id, "🎮 ወደ ይሳቃል ቢንጎ እንኳን ደህና መጡ! ጨዋታውን ለመጀመር ከታች ያለውን ቁልፍ ይጫኑ።")
        
        # ዎሌት ማሳያ
        elif 'ዎሌት' in text or 'Balance' in text:
            wallet_amt = users_db[user_id]["wallet"]
            send_telegram_message(chat_id, f"💰 የዎሌት ሒሳብዎ: **{wallet_amt} ብር** ነው።")
        
        # ሂሳብ መሙላት (Deposit) ጀማሪ ትዕዛዝ
        elif 'መሙላት' in text or 'Deposit' in text:
            user_states[user_id] = {"action": "waiting_for_amount"}
            send_telegram_message(chat_id, "💳 ሂሳብ ለመሙላት ከ **50 እስከ 3000 ብር** ድረስ ማስገባት የሚፈልጉትን የብር መጠን ቁጥር ብቻ (ለምሳሌ: 500) ይጻፉልን።")
        
        # ገንዘብ ማውጣት
        elif 'ማውጣት' in text or 'Withdraw' in text:
            send_telegram_message(chat_id, "💸 ገንዘብ ለማውጣት የሚፈልጉትን መጠን ይጻፉ (አስተዳዳሪው ያረጋግጥልዎታል)።")
        
        # ሐ) ተጠቃሚው የዲፖዚት መጠን ቁጥር ሲልክ (ለምሳሌ 500)
        elif user_states.get(user_id, {}).get("action") == "waiting_for_amount":
            try:
                amount = float(text)
                if 50 <= amount <= 3000:
                    user_states[user_id] = {"action": "awaiting_screenshot", "amount": amount}
                    
                    bank_info = (
                        f"💳 **የገንዘብ ማስተላለፊያ አካውንቶች ({amount} ብር):**\n\n"
                        f"🏦 **CBE (የንግድ ባንክ):** `1000783589277`\n"
                        f"👤 ስም: Abinet Mifeta\n\n"
                        f"📱 **Telebirr:** `0955358565`\n"
                        f"👤 ስም: Abinet\n\n"
                        f"⚠️ **ማሳሰቢያ:** ከላይ ባሉት አካውንቶች ገንዘቡን ገቢ ካደረጉ በኋላ **የክፍያ ማረጋገጫ (Screenshot)** ፎቶ በዚህ ቦት ላይ ይላኩ!"
                    )
                    send_telegram_message(chat_id, bank_info)
                else:
                    send_telegram_message(chat_id, "⚠️ እባክዎ ከ **50 እስከ 3000 ብር** መካከል ትክክለኛ መጠን ያስገቡ።")
            except ValueError:
                send_telegram_message(chat_id, "⚠️ እባክዎ ትክክለኛ የቁጥር መጠን ብቻ ይላኩ (ለምሳሌ: 500)።")
        
        else:
            send_telegram_message(chat_id, "ሰላም! ትዕዛዝዎ አልገባም፤ ዎሌትዎን ለማየት 'ዎሌት' ይበሉ ወይም 'ጨዋታ ጅምር' የሚለውን ይጫኑ።")

    return jsonify({"status": "success"})

# የቴሌግራም መልዕክት መላኪያ ሄፐር
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error: {e}")

# ሚኒ አፕ (Mini App) መክፈቻ ቁልፍ (Button) ያለው መልዕክት
def send_webapp_button(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "🎮 ይሳቃል ቢንጎ (Mini App) ክፈት", "web_app": {"url": "https://yisakal-bingo7.onrender.com"}}]
            ]
        }
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error: {e}")

# ስክሪንሾቱን እና የዲፖዚት ጥያቄውን ለአድሚን መላክ (ከአስተዳደር ማጽደቂያ ቁልፍ ጋር)
def forward_deposit_to_admin(user_id, amount, photo_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    caption = f"🔔 **አዲስ የዲፖዚት ጥያቄ!**\n\n👤 ተጠቃሚ ID: `{user_id}`\n💰 የጠየቀው መጠን: **{amount} ብር**\n\nእባክዎ ትክክል መሆኑን አረጋግጦ ከታች ያለውን ቁልፍ ይጫኑ።"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "photo": photo_id,
        "caption": caption,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": f"✅ አጽድቅ (+{amount} ብር)", "callback_data": f"app_{user_id}_{amount}"}]
            ]
        }
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error forwarding to admin: {e}")

def answer_callback(callback_query_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_query_id, "text": text, "show_alert": True})
    except Exception as e:
        print(f"Error: {e}")

# API Endpoints ለ Mini App
@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    user = users_db.get(user_id, {"username": "Player", "wallet": 0.0, "bonus": 0, "phone": "የግል"})
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
        users_db[user_id] = {"username": "Player", "wallet": 0.0, "bonus": 0, "phone": "የግል"}

    if users_db[user_id]["wallet"] < 10:
        return jsonify({"success": False, "message": "⚠️ በቂ ገንዘብ የለዎትም! እባክዎ ዎሌትዎን ይሙሉን።"})

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
