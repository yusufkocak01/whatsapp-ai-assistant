# app.py
import os
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials
import re

app = Flask(__name__)

# Google Sheets erişim bilgisi (Railway'de .env'den alınacak)
GOOGLE_SHEETS_ID = "1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc"
SERVICE_ACCOUNT_INFO = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if SERVICE_ACCOUNT_INFO:
    creds = Credentials.from_service_account_info(
        json.loads(SERVICE_ACCOUNT_INFO),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    gc = gspread.authorize(creds)
else:
    gc = None

def normalize_text(text):
    """Küçük harfe çevir, fazla boşlukları temizle"""
    return re.sub(r'\s+', ' ', text.strip().lower())

def find_response(user_message):
    if not gc:
        return "Bot yapılandırılmamış."
    
    try:
        sheet = gc.open_by_key(GOOGLE_SHEETS_ID)
        worksheets = sheet.worksheets()
    except Exception as e:
        return f"Sayfa açılamadı: {str(e)}"

    normalized_input = normalize_text(user_message)

    for ws in worksheets:
        try:
            # İlk satırda başlıklar olmalı: keyword, rules, link
            records = ws.get_all_records()
        except:
            continue  # Başlık eksikse atla

        for row in records:
            keyword = normalize_text(str(row.get("keyword", "")).strip())
            if not keyword:
                continue
            # Tam eşleşme veya içeriyorsa
            if keyword == normalized_input or keyword in normalized_input:
                rules = str(row.get("rules", "")).strip()
                link = str(row.get("link", "")).strip()
                if link and link.lower() not in ["", "none", "null"]:
                    if not link.startswith("http"):
                        link = "https://" + link
                    rules += "\n\n" + link
                return rules
    return None

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    if not incoming_msg:
        msg.body("Merhaba! Size nasıl yardımcı olabilirim?")
    else:
        response = find_response(incoming_msg)
        if response:
            msg.body(response)
        else:
            # Varsayılan menü (eşleşme yoksa)
            msg.body(
                "Merhaba! 👋 Yusuf’un Dijital Asistanıyım.\n\n"
                "Lütfen ilgilendiğiniz hizmeti seçin:\n"
                "1️⃣ Organizasyon\n"
                "2️⃣ Davet Evi\n"
                "3️⃣ Stres Evi\n"
                "4️⃣ Proje\n"
                "5️⃣ Seslendirme\n"
                "6️⃣ Metin\n"
                "7️⃣ Mentorluk"
            )
    return str(resp)

# Railway için sağlık kontrolü
@app.route("/", methods=["GET"])
def health_check():
    return "✅ Bot çalışıyor!"

if __name__ == "__main__":
    app.run(debug=True)
