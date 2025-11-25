from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import requests
import os

app = Flask(__name__)

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Google Sheets
CREDS_PATH = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
sheets_creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
sheets_client = gspread.authorize(sheets_creds)

def get_all_prompts():
    """Google Sheets'te A sütunundaki tüm dolu hücreleri al"""
    try:
        sheet = sheets_client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        all_cells = sheet.col_values(1)  # A sütunu = 1
        # Boş olmayan tüm hücreleri al (başlık varsa 1. satırı atla isterseniz)
        prompts = [cell.strip() for cell in all_cells if cell and cell.strip()]
        return "\n\n".join(prompts)
    except Exception as e:
        print(f"Google Sheets hatası: {e}")
        return "Sen Yusuf'un Dijital Asistanısın. Kısa ve samimi cevaplar ver."

def get_gemini_response(user_message, full_prompt):
    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": (
                        f"Aşağıdaki kurallara göre cevap ver. Kurallar mutlaka uygulanacak.\n\n"
                        f"KURALLAR:\n{full_prompt}\n\n"
                        f"KULLANICI MESAJI: \"{user_message}\"\n\n"
                        "Cevabın 1-3 cümle, Türkçe, samimi ve profesyonel olsun. Kuralları unutma."
                    )
                }]
            }],
            "safetySettings": [
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            ]
        }
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Gemini hatası: {e}")
        return "Şu an yardımcı olamıyorum. Lütfen 'stres evi', 'davet evi' veya 'proje' yazın."

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming_msg = request.form.get('Body', '').strip()
    print(f"Gelen mesaj: {incoming_msg}")

    full_prompt = get_all_prompts()
    reply = get_gemini_response(incoming_msg, full_prompt)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply}</Message>
</Response>""", 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "✅ Tek Sütun Prompt Sistemi Aktif"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
