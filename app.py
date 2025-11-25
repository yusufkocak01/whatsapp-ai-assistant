from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import requests
import os
import json
import tempfile

app = Flask(__name__)

# 🔧 Ayarlar (düzeltildi: fazladan boşluklar kaldırıldı)
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 🧾 Google Sheets kimlik doğrulama (Railway uyumlu)
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("GOOGLE_CREDENTIALS_JSON ortam değişkeni eksik!")

# Geçici dosya olarak credentials oluştur
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tf:
    json.dump(creds_dict, tf)
    temp_creds_path = tf.name

# ✅ Scope'da fazladan boşluk yok!
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
try:
    sheets_creds = Credentials.from_service_account_file(temp_creds_path, scopes=SCOPES)
    sheets_client = gspread.authorize(sheets_creds)
except Exception as e:
    print(f"Google Auth hatası: {e}")
    sheets_client = None

def get_all_prompts():
    if not sheets_client:
        return "Sen Yusuf'un Dijital Asistanısın. Kısa ve samimi cevaplar ver."
    try:
        sheet = sheets_client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        all_cells = sheet.col_values(1)  # A sütunu
        prompts = [cell.strip() for cell in all_cells if cell and cell.strip()]
        return "\n\n".join(prompts)
    except Exception as e:
        print(f"Google Sheets okuma hatası: {e}")
        return "Sen Yusuf'un Dijital Asistanısın. Size nasıl yardımcı olabilirim?"

def get_gemini_response(user_message, full_prompt):
    if not GEMINI_API_KEY:
        return "Gemini API anahtarı eksik."

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
        response_data = r.json()
        if 'candidates' in response_data and response_data['candidates']:
            return response_data['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            return "Anladım, ancak şu anda size yardımcı olamıyorum."
    except Exception as e:
        print(f"Gemini API hatası: {e}")
        return "Dijital asistanım şu anda bir sorunla karşılaştı. Lütfen daha sonra tekrar deneyin."

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        incoming_msg = request.form.get('Body', '').strip()
        print(f"📩 Gelen mesaj: {incoming_msg}")

        full_prompt = get_all_prompts()
        reply = get_gemini_response(incoming_msg, full_prompt)

    except Exception as e:
        print(f"Webhook genel hatası: {e}")
        reply = "Merhaba! Şu anda geçici bir teknik sorun yaşıyoruz. Lütfen birkaç dakika sonra tekrar yazın."

    # 📤 Twilio için geçerli TwiML XML yanıtı
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply}</Message>
</Response>""", 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "✅ Yusuf'un AI Asistanı çalışıyor"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
# Google credentials eklendi - 2025-04-05
