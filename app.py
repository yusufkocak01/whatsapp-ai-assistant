from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials
import requests
import os

app = Flask(__name__)

# ===== Ayarlar =====
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"
TWILIO_PHONE_NUMBER = "+14155238886"  # Sandbox numarası
OPENROUTER_API_KEY = "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"
OPENROUTER_MODEL = "openai/gpt-4o-mini"

# Google Sheets
CREDS_PATH = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
client = gspread.authorize(creds)

def get_prompt_from_sheet(user_message):
    try:
        sheet = client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        rows = sheet.get_all_records()
        user_msg = user_message.lower().strip()
        for row in rows:
            keyword = str(row.get("anahtar kelime", "")).strip().lower()
            prompt = str(row.get("aciklama", "")).strip()
            if keyword and keyword in user_msg:
                return prompt
    except Exception as e:
        print(f"Sheet hatası: {e}")
    return "Sen Yusuf'un Dijital Asistanısın. Kullanıcıya 'Merhaba! Size nasıl yardımcı olabilirim?' de, samimi ve profesyonel ol."

def get_ai_response(prompt):
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": "Yusuf'un dijital asistanısın. Kısa, net, yardımcı ve sıcak cevaplar ver."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 300,
                "temperature": 0.6
            }
        )
        return resp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return "Şu an yanıt veremiyorum. Lütfen daha sonra tekrar deneyin."

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming_msg = request.form.get('Body', '').strip()
    from_number = request.form.get('From', '')
    
    print(f"[{from_number}] → {incoming_msg}")
    
    prompt = get_prompt_from_sheet(incoming_msg)
    ai_reply = get_ai_response(prompt)
    
    # Twilio'ya cevap gönder (XML formatında)
    response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{ai_reply}</Message>
</Response>"""
    
    return response_xml, 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "Yusuf'un WhatsApp Asistanı çalışıyor ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

