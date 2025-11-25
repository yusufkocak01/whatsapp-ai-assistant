from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import requests
import os

app = Flask(__name__)

# === Ayarlar ===
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"
TWILIO_PHONE_NUMBER = "+14155238886"

# Google Sheets kimlik doğrulama
CREDS_PATH = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
sheets_creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
sheets_client = gspread.authorize(sheets_creds)

def get_prompt_from_sheet(user_message):
    """Kullanıcı mesajına göre Google Sheets'ten prompt al"""
    try:
        sheet = sheets_client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        rows = sheet.get_all_records()
        user_msg = user_message.lower().strip()
        for row in rows:
            keyword = str(row.get("anahtar kelime", "")).strip().lower()
            prompt = str(row.get("aciklama", "")).strip()
            if keyword and keyword in user_msg:
                return prompt
    except Exception as e:
        print(f"Google Sheets hatası: {e}")
    # Varsayılan prompt
    return "Sen Yusuf'un Dijital Asistanısın. Kullanıcıya 'Merhaba! Size nasıl yardımcı olabilirim?' de. Konu belirtin: stres evi, davet evi, proje, mentor, vs."

def get_gemini_response(prompt):
    """Gemini 1.5 Flash ile cevap üret"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Sistem hatası: AI anahtarı eksik."
    
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{
                "text": (
                    "Sen Yusuf Koçak'ın dijital asistanısın. Aşağıdaki talimata göre kullanıcıya kısa (2-3 cümle), net, samimi ve profesyonel bir cevap ver.\n\n"
                    "Talimat: " + prompt
                )
            }]
        }],
        "safetySettings": [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        ]
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Gemini hatası: {e}")
        return "Şu an size yardımcı olamıyorum. Lütfen 'stres evi', 'davet evi' veya 'proje' gibi bir konu belirtin."

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming_msg = request.form.get('Body', '').strip()
    print(f"Gelen mesaj: {incoming_msg}")

    prompt = get_prompt_from_sheet(incoming_msg)
    reply = get_gemini_response(prompt)

    # Twilio XML cevabı
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply}</Message>
</Response>""", 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "Yusuf'un WhatsApp Asistanı (Gemini) çalışıyor ✅"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
