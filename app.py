from flask import Flask, request
import requests
import os
import csv

app = Flask(__name__)

# 🔑 Gemini API anahtarı (Railway Variables'te tanımlı olmalı)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY ortam değişkeni eksik!")

# 📥 CSV'den keyword → rule eşlemelerini yükle
def load_rules():
    rules = {}
    try:
        with open("prompt.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                keyword = row["keyword"].strip().lower()
                rule = row["rule"].strip()
                rules[keyword] = rule
        print("✅ Kurallar yüklendi:", list(rules.keys()))
    except Exception as e:
        print("❌ CSV okuma hatası:", e)
        rules = {"default": "Yusuf'un dijital asistanıyım."}
    return rules

# Global kural seti (her başlatmada bir kez yüklenir)
RULES = load_rules()

def get_ai_response(user_message, instruction):
    """Gemini'ye kullanıcı mesajı + talimatı gönderir."""
    try:
        full_prompt = (
            f"TALİMAT: {instruction}\n\n"
            f"KULLANICI MESAJI: {user_message}\n\n"
            "Cevabın 1-3 cümle, Türkçe, samimi, doğal ve profesyonel olsun. "
            "Asla 'size nasıl yardımcı olabilirim?' gibi kalıplar kullanma."
        )
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "safetySettings": [
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            ]
        }
        response = requests.post(url, json=payload, timeout=8)
        response.raise_for_status()
        data = response.json()
        if 'candidates' in data and data['candidates']:
            return data['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            return "Anladım, ama şu an cevap veremiyorum."
    except Exception as e:
        print("Gemini hatası:", e)
        return "Dijital asistanım şu anda bir sorunla karşılaştı."

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        incoming_msg = request.form.get('Body', '').strip()
        print(f"📩 Gelen mesaj: '{incoming_msg}'")

        if not incoming_msg:
            reply = "Boş mesaj gönderdiniz."
        else:
            # Küçük harfe çevirip CSV'de ara
            instruction = RULES.get(incoming_msg.lower(), RULES.get("default", "Kullanıcıya doğal ve yardımcı bir cevap ver."))
            reply = get_ai_response(incoming_msg, instruction)

    except Exception as e:
        print("Webhook hatası:", e)
        reply = "İşlem sırasında teknik bir sorun oluştu."

    # 📤 Twilio için TwiML yanıtı
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply}</Message>
</Response>""", 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "✅ Yusuf'un AI Asistanı (prompt.csv + Gemini)"

if __name__ == '__main__':
    # 🚧 Port 8080 olarak sabitlendi (Railway'de Networking → Port: 8080 olmalı)
    app.run(host='0.0.0.0', port=8080)
