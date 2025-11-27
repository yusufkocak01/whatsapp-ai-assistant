# app.py
import os
import json
import re
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Google Sheets ID (sizin sheet)
GOOGLE_SHEETS_ID = "1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc"

# Google Sheets erişimi
SERVICE_ACCOUNT_INFO = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if SERVICE_ACCOUNT_INFO:
    try:
        creds = Credentials.from_service_account_info(
            json.loads(SERVICE_ACCOUNT_INFO),
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        gc = gspread.authorize(creds)
    except Exception as e:
        print("❗ Google Auth hatası:", e)
        gc = None
else:
    gc = None

def normalize_text(text):
    """Küçük harfe çevir, fazla boşluğu tek boşluğa indir"""
    return re.sub(r'\s+', ' ', text.strip().lower())

def find_response(user_message):
    if not gc:
        return "Asistan yapılandırılmamış. Lütfen yöneticiyle iletişime geçin."

    try:
        sheet = gc.open_by_key(GOOGLE_SHEETS_ID)
        worksheets = sheet.worksheets()
    except Exception as e:
        print("❗ Sheet açma hatası:", e)
        return "Veri kaynağına erişilemiyor."

    normalized_input = normalize_text(user_message)

    for ws in worksheets:
        try:
            records = ws.get_all_records()
        except:
            continue  # Başlık eksikse bu sekme atlanır

        for row in records:
            try:
                keyword = normalize_text(str(row.get("keyword", "")).strip())
                if not keyword:
                    continue
                # Tam eşleşme ÖNCESİ: önce "tam eşleşme" kontrol et, sonra "içerme"
                if keyword == normalized_input or keyword in normalized_input:
                    rules = str(row.get("rules", "")).strip()
                    link = str(row.get("link", "")).strip()
                    if link and link.lower() not in ["", "none", "null"]:
                        if not link.startswith(("http://", "https://")):
                            link = "https://" + link
                        rules += "\n\n" + link
                    return rules
            except Exception as row_error:
                print(f"❗ Satır hatası ({ws.title}):", row_error)
                continue
    return None

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    if not incoming_msg:
        fallback = (
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
        msg.body(fallback)
    else:
        response = find_response(incoming_msg)
        if response:
            msg.body(response)
        else:
            # Eşleşme yoksa menü göster
            fallback = (
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
            msg.body(fallback)
    return str(resp)

@app.route("/", methods=["GET"])
def health_check():
    return "✅ WhatsApp Asistan çalışıyor! Webhook: /webhook"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Railway PORT'u kullan, yoksa 8080
    app.run(host="0.0.0.0", port=port, debug=False)
