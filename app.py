from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import os
import json
import tempfile

app = Flask(__name__)

# 🔧 Ayarlar
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"

# 🧾 Google Sheets kimlik doğrulama
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("GOOGLE_CREDENTIALS_JSON ortam değişkeni eksik!")

creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tf:
    json.dump(creds_dict, tf)
    temp_creds_path = tf.name

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
try:
    sheets_creds = Credentials.from_service_account_file(temp_creds_path, scopes=SCOPES)
    sheets_client = gspread.authorize(sheets_creds)
except Exception as e:
    print(f"Google Auth hatası: {e}")
    sheets_client = None

def get_reply_from_sheet(user_message):
    """Kullanıcı mesajını Google Sheets'te A sütununda arar, B sütunundan cevap döner."""
    if not sheets_client:
        return "Google Sheets bağlantısı kurulamadı."
    
    try:
        sheet = sheets_client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        # A sütunu: anahtar kelimeler, B sütunu: açıklamalar
        keywords = sheet.col_values(1)  # A sütunu
        replies = sheet.col_values(2)   # B sütunu

        user_lower = user_message.strip().lower()

        for i, keyword in enumerate(keywords):
            if not keyword:
                continue
            # Tam eşleşme veya içeriyorsa (istediğin gibi ayarlayabilirsin)
            if user_lower == keyword.lower().strip():
                if i < len(replies) and replies[i]:
                    return replies[i]
                else:
                    return "Bu anahtar kelime için açıklama tanımlanmamış."
        
        return "Malesef bu konuda bilgim yok. 'yardım' yazarak destek alabilirsiniz."

    except Exception as e:
        print(f"Google Sheets okuma hatası: {e}")
        return "Veri tabanıma erişim sırasında teknik bir sorun oluştu."

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        incoming_msg = request.form.get('Body', '').strip()
        print(f"📩 Gelen mesaj: {incoming_msg}")

        if not incoming_msg:
            reply = "Boş mesaj gönderdiniz."
        else:
            reply = get_reply_from_sheet(incoming_msg)

    except Exception as e:
        print(f"Webhook hatası: {e}")
        reply = "İşlem sırasında bir hata oluştu. Lütfen tekrar deneyin."

    # 📤 Twilio için TwiML yanıtı
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply}</Message>
</Response>""", 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "✅ Yusuf'un Anahtar Kelime Asistanı çalışıyor"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
