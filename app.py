# app.py
import os
import csv
import io
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import re

app = Flask(__name__)

# 🔁 Kendi GitHub raw linkini buraya yaz!
GITHUB_CSV_URL = "https://raw.githubusercontent.com/yusufkocak01/whatsapp-ai-assistant/main/prompt.csv"

def load_rules():
    try:
        response = requests.get(GITHUB_CSV_URL, timeout=10)
        response.raise_for_status()
        content = response.content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        rules = []
        for row in reader:
            if row.get("keyword") and row.get("rules"):
                rules.append({
                    "keyword": row["keyword"].strip(),
                    "rules": row["rules"].strip(),
                    "link": row.get("link", "").strip()
                })
        return rules
    except Exception as e:
        print("❗ CSV yüklenemedi:", e)
        return None

def normalize_text(text):
    return re.sub(r'\s+', ' ', text.strip().lower())

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    # Boş mesaj gelirse cevap verme
    if not incoming_msg:
        return str(resp)

    rules_list = load_rules()
    if rules_list is None:
        # Opsiyonel: hata durumunda bile sessiz kal veya kısa mesaj döndür
        return str(resp)

    normalized_input = normalize_text(incoming_msg)

    # Önce TAM eşleşme
    for rule in rules_list:
        kw = normalize_text(rule["keyword"])
        if kw == normalized_input:
            response_text = rule["rules"]
            link = rule["link"]
            if link and link.lower() not in ["", "none", "null"]:
                if not link.startswith(("http://", "https://")):
                    link = "https://" + link
                response_text += "\n\n" + link
            msg.body(response_text)
            return str(resp)

    # Sonra İÇERME eşleşmesi
    for rule in rules_list:
        kw = normalize_text(rule["keyword"])
        if kw and kw in normalized_input:
            response_text = rule["rules"]
            link = rule["link"]
            if link and link.lower() not in ["", "none", "null"]:
                if not link.startswith(("http://", "https://")):
                    link = "https://" + link
                response_text += "\n\n" + link
            msg.body(response_text)
            return str(resp)

    # ❌ Hiçbir eşleşme yok → **Cevap verme**
    # (İstersen aşağıdaki yorumu kaldırarak "Anlamadım" mesajı eklenebilir)
    # msg.body("Mesajınızı anlayamadım. Lütfen geçerli bir anahtar kelime kullanın.")
    return str(resp)

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Sadece CSV'ye sadık WhatsApp Asistan çalışıyor!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

