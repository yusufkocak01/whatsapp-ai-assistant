from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import os

app = Flask(__name__)

# === Ayarlar ===
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"
TWILIO_PHONE_NUMBER = "+14155238886"

# Google Sheets bağlantısı
CREDS_PATH = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
client = gspread.authorize(creds)

def get_response_from_sheet(user_message):
    """Kullanıcı mesajına göre Google Sheets'ten direkt cevap al"""
    try:
        sheet = client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        rows = sheet.get_all_records()
        user_lower = user_message.lower().strip()

        for row in rows:
            keyword = str(row.get("anahtar kelime", "")).strip().lower()
            response_text = str(row.get("aciklama", "")).strip()
            if keyword and keyword in user_lower:
                return response_text

    except Exception as e:
        print(f"Google Sheets hatası: {e}")

    # Varsayılan cevap
    return "Merhaba! Ben Yusuf'un Dijital Asistanıyım. Size nasıl yardımcı olabilirim?\nÖrneğin şunlardan birini yazabilirsiniz:\n- stres evi\n- davet evi\n- proje\n- mentor\n- fiyat\n- randevu"

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming_msg = request.form.get('Body', '').strip()
    print(f"Gelen mesaj: {incoming_msg}")

    # Google Sheets'ten cevap al
    reply = get_response_from_sheet(incoming_msg)

    # Twilio'ya XML cevap
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply}</Message>
</Response>""", 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "Yusuf'un WhatsApp Asistanı çalışıyor ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
