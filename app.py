from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials
import requests
import os

# Flask app
app = Flask(__name__)

# ====== AYARLAR ======
TWILIO_PHONE_NUMBER = "+14155238886"
OPENROUTER_API_KEY = "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"
OPENROUTER_MODEL = "openai/gpt-4o-mini"

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"  # Sadece bu sekme kullanılıyor

# Google Sheets auth
CREDS_PATH = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
client = gspread.authorize(creds)

# ====== FONKSİYONLAR ======

def get_rows_from_sheet():
    """'baslangic' sekmesinden tüm satırları al"""
    try:
        sheet = client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        return sheet.get_all_records()
    except Exception as e:
        print(f"Google Sheets hatası: {e}")
        return []

def find_prompt(user_message):
    """Kullanıcı mesajına göre ilk eşleşen prompt'u döndür"""
    rows = get_rows_from_sheet()
    user_lower = user_message.lower().strip()

    for row in rows:
        try:
            keyword = str(row.get("anahtar kelime", "")).strip().lower()
            prompt = str(row.get("aciklama", "")).strip()
            if keyword and keyword in user_lower:
                return prompt
        except Exception as e:
            continue  # Bozuk satırı atla

    # Hiçbir şey bulunamazsa varsayılan prompt
    return (
        "Sen Yusuf'un Dijital Asistanısın. Kullanıcıya 'Merhaba! Size nasıl yardımcı olabilirim?' diye samimi ve profesyonel bir şekilde cevap ver. "
        "Lütfen konu belirtin: örneğin 'stres evi', 'davet evi', 'proje', 'mentor', 'fiyat', 'randevu' gibi."
    )

def get_ai_response(prompt):
    """OpenRouter ile AI cevabı al"""
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": "Sen Yusuf'un Dijital Asistanısın. Kısa, net, samimi ve yardımsever cevaplar ver."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 300,
                "temperature": 0.6
            }
        )
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"AI hatası: {e}")
        return "Üzgünüm, şu anda cevap veremiyorum. Lütfen daha sonra tekrar yazın."

# ====== TWILIO WEBHOOK ======

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming_msg = request.form.get('Body', '').strip()
    from_number = request.form.get('From', '')
    
    print(f"[{from_number}] → {incoming_msg}")

    prompt = find_prompt(incoming_msg)
    ai_response = get_ai_response(prompt)

    # Twilio ile cevap gönder
    try:
        from twilio.rest import Client
        # Twilio SID ve Token’i Render ortam değişkenlerinden al (güvenlik için)
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID', 'MJ46TL4XKBY3S7BEAJUK6SNJ')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        if not auth_token:
            raise ValueError("TWILIO_AUTH_TOKEN eksik")
        
        twilio_client = Client(account_sid, auth_token)
        twilio_client.messages.create(
            body=ai_response,
            from_=TWILIO_PHONE_NUMBER,
            to=from_number
        )
    except Exception as e:
        print(f"Twilio gönderim hatası: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "ok"}), 200

@app.route('/')
def index():
    return "Yusuf'un WhatsApp Dijital Asistanı çalışıyor ✅"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
