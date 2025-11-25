from flask import Flask, request
import openai
import os
import csv

app = Flask(__name__)

# 🔑 OpenAI API Anahtarı (Railway Variables'te tanımlı olmalı)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY ortam değişkeni eksik!")

# OpenAI istemcisini başlat
client = openai.OpenAI(api_key=OPENAI_API_KEY)

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

def get_chatgpt_response(user_message, rule_instruction):
    """ChatGPT ile akıllı cevap üretir."""
    try:
        system_message = (
            "Sen Yusuf'un Dijital Asistanısın. Aşağıdaki talimata göre cevap ver. "
            "Cevabın 1-3 cümle, Türkçe, samimi, doğal ve profesyonel olsun. "
            "Hiçbir zaman 'size nasıl yardımcı olabilirim?' gibi kalıplar kullanma."
        )
        user_prompt = f"TALİMAT: {rule_instruction}\n\nKULLANICI MESAJI: {user_message}"

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("🚨 ChatGPT Hatası:", e)
        return "Dijital asistanım şu anda bir sorunla karşılaştı."

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        incoming_msg = request.form.get('Body', '').strip()
        print(f"📩 Gelen mesaj: '{incoming_msg}'")

        if not incoming_msg:
            reply = "Boş mesaj gönderdiniz."
        else:
            rule = RULES.get(incoming_msg.lower(), RULES.get("default", "Kullanıcıya yardımcı ol."))
            reply = get_chatgpt_response(incoming_msg, rule)

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
    return "✅ Yusuf'un AI Asistanı (prompt.csv + ChatGPT)"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
