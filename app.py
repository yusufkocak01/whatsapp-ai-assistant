from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Google Sheets bağlantısı
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_file(
    "credentials.json",
    scopes=SCOPES
)
client = gspread.authorize(creds)

# ---- GOOGLE SHEETS AYARLARI ----
SHEET_NAME = "WhatsAppBot"  # Google Sheet dosyanın adı
WORKSHEET_NAME = "Veriler"  # Mesaj–cevap tablo sayfası

sheet = client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)


def get_sheet_reply(user_message):
    """
    Google Sheets içinde A sütunundaki kelimeyi arar.
    Karşılık gelen B sütunu değerini döndürür.
    """

    try:
        records = sheet.get_all_records()
    except Exception as e:
        return f"Google Sheets okunamıyor: {e}"

    user_message = user_message.lower().strip()

    for row in records:
        keyword = str(row.get("kelime", "")).lower().strip()
        reply = str(row.get("cevap", "")).strip()

        if keyword in user_message:
            return reply

    return None  # eşleşme yoksa


@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.values.get("Body", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    reply = get_sheet_reply(incoming_msg)

    if reply:
        msg.body(reply)
    else:
        msg.body("Sizi anlıyorum. Bilgiyi Google Sheets'te bulamadım. Lütfen daha net bir kelime yazın.")

    return str(resp)


@app.route("/", methods=["GET"])
def home():
    return "WhatsApp bot çalışıyor."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
