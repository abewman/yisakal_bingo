from flask import Flask, render_template_string, request, jsonify
import os

app = Flask(__name__)

# ለጊዜው መረጃዎችን በግንዛቤ (Memory) ለመያዝ የሚረዱ 딕ሽነሪዎች (Databases)
users_db = {
    "8416118350": {"username": "አብነት", "wallet": 100, "bonus": 10, "phone": "+2519********"}
}

game_state = {
    "booked": [],       # የተያዙ ካርቴላዎች ቁጥሮች (ለምሳሌ [12, 45])
    "active_players": 1,
    "game_status": "waiting", # waiting ወይም finished
    "winner_id": None
}

# 1. የፊት ገጽታውን (index.html) በቀጥታ ከሰርቨር ማشለፊያ
@app.route('/')
def home():
    # index.html ፋይል ውስጥ ያለውን ኮድ በቀጥታ ማንበብ እንዲችል ወይም መልዕክት እንዲያሳይ
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "ይሳቃል ቢንጎ ሰርቨር በትክክል እየሰራ ነው! (index.html ፋይል አልተገኘም)"

# 2. የተጠቃሚ መረጃ ማግኛ API
@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    user = users_db.get(user_id)
    if not user:
        # አዲስ ተጫዋች ሲመጣ በራስሰር ጀማሪ ዎሌት መፍጠር
        user = {"username": f"Player_{user_id[-4:]}", "wallet": 100, "bonus": 0, "phone": "የግል"}
        users_db[user_id] = user
    
    return jsonify({
        "success": True,
        "username": user["username"],
        "wallet": user["wallet"],
        "bonus": user["bonus"],
        "phone": user["phone"]
    })

# 3. የተያዙ ካርቴላዎች እና የጨዋታ ሁኔታ ማግኛ API
@app.route('/api/booked', methods=['GET'])
def get_booked():
    return jsonify({
        "booked": game_state["booked"],
        "active_players": len(game_state["booked"]) if len(game_state["booked"]) > 0 else 1,
        "game_status": game_state["game_status"],
        "winner_id": game_state["winner_id"]
    })

# 4. ካርቴላ የመምረጥ እና የመያዝ API (10 ብር ተቀናሽ)
@app.route('/api/book', methods=['POST'])
def book_cartela():
    data = request.json
    user_id = str(data.get('user_id'))
    cartela_num = int(data.get('cartela_num'))

    if cartela_num in game_state["booked"]:
        return jsonify({"success": False, "message": f"⚠️ ካርቴላ ቁጥር #{cartela_num} უკვე በሌላ ተጫዋች ተይዟል!"})

    # ተጠቃሚውን ማረጋገጥ
    if user_id not in users_db:
        users_db[user_id] = {"username": f"Player_{user_id[-4:]}", "wallet": 100, "bonus": 0, "phone": "የግል"}

    if users_db[user_id]["wallet"] < 10:
        return jsonify({"success": False, "message": "⚠️ በቂ ገንዘብ (Wallet) የለዎትም! እባክዎ ዎሌትዎን ይሙሉን።"})

    # 10 ብር መቀነስ እና ካርቴላውን መዝገብ ውስጥ ማስገባት
    users_db[user_id]["wallet"] -= 10
    game_state["booked"].append(cartela_num)

    return jsonify({"success": True, "message": f"ካርቴላ #{cartela_num} ተይዟል!"})

# 5. አሸናፊ ሆኖ ሲመዘገብ የሽልማት ገንዘብ መጨመሪያ API
@app.route('/api/win', methods=['POST'])
def declare_win():
    data = request.json
    user_id = str(data.get('user_id'))
    prize = float(data.get('prize', 50))

    if user_id in users_db:
        users_db[user_id]["wallet"] += prize
    
    game_state["game_status"] = "finished"
    game_state["winner_id"] = user_id

    return jsonify({"success": True, "message": "ሽልማቱ ተጨምሯል!"})

# 6. ጨዋታውን ዳግም የማስጀመሪያ API (Reset)
@app.route('/api/reset_game', methods=['POST'])
def reset_game():
    game_state["booked"] = []
    game_state["game_status"] = "waiting"
    game_state["winner_id"] = None
    return jsonify({"success": True, "message": "ጨዋታው ታድሷል!"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
