from flask import Flask, request
import requests
import os
import csv

app = Flask(__name__)

# 🔑 GEMINI API Anahtarı (Railway Variables'te tanımlı olmalı)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY ortam değişkeni eksik!")

# 📥 prompt.csv dosyasını yükle
def load_rules_from_csv():
    rules = {}
    try:
        with open("prompt.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                keyword = row["keyword"].strip().lower()
                rule = row["rule"].strip()
                rules[keyword] = rule
        print("✅ prompt.csv yüklendi. Anahtar kelimeler:", list(rules.keys()))
    except Exception as e:
        print("❌ prompt.csv okunamadı:", e)
        rules = {"default": "Yusuf'un dijital asistanıyım."}
    return rules

# Kuralları uygulama başlangıcında yükle
RULES = load_rules_from_csv()

def get_gemini_response(user_message, rule_instruction):
    """Gemini API’si ile akıllı cevap üretir."""
    try:
        full_prompt = (
            f"TALİMAT: {rule_instruction}\n\n"
            f"KULLANICI MESAJI: {user_message}\n\n"
            "Cevabın 1-3 cümle, Türkçe, samimi, doğal ve profesyonel olsun. "
            "Hiçbir zaman 'size nasıl yardımcı olabilirim?' gibi kalıplar kullanma."
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
            return "Anladım, ancak şu anda yardımcı olamıyorum."
    except Exception as e:
        print("🚨 Gemini Hatası:", e)
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
            rule = RULES.get(incoming_msg.lower(), RULES.get("default", "Kullanıcıya yardımcı ol."))
            reply = get_gemini_response(incoming_msg, rule)

    except Exception as e:
        print("🚨 Webhook Hatası:", e)
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
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

