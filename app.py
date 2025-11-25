from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import requests
import os

app = Flask(__name__)

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit?usp=sharing"
SHEET_NAME = "baslangic"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Google Sheets bağlantısı
CREDS_PATH = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
sheets_creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
sheets_client = gspread.authorize(sheets_creds)

def find_matching_prompt(user_message):
    """Google Sheets'teki her hücreyi oku, ilk eşleşeni döndür"""
    try:
        sheet = sheets_client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
        # Tüm hücreleri A sütunundan al (sadece ilk sütun)
        all_values = sheet.col_values(1)  # A sütunu = 1. sütun

        # İlk satır başlık olabilir → atla (opsiyonel)
        prompts = all_values[1:] if len(all_values) > 1 else all_values

        user_msg_lower = user_message.lower().strip()

        # Her prompt satırını kontrol et
        for prompt in prompts:
            prompt = prompt.strip()
            if not prompt:
                continue

            # Eğer prompt içinde "eğer X derse" gibi kurallar varsa,
            # onunla değil — kullanıcı mesajının içindeki anahtar kelimelerle eşleşme yapacağız.
            # Bunun yerine: her prompt kendisi bir talimat.
            # AMA: kullanıcı mesajında geçen kelimeler bu prompt ile ilişkili olmalı.

            # ÖNEMLİ: Bu versiyonda, HER SATIR doğrudan bir "sistem talimatı" olarak AI’ya verilir.
            # Yani: kullanıcı mesajına bakmadan, her zaman tüm prompt’lar geçerli olur.
            # → Bu istemediğiniz bir şey olabilir.

        # ✅ DOĞRU YAKLAŞIM: Kullanıcı mesajına göre ilgili satırı seçmek.
        # Ama siz "her hücre bir prompt" dediniz → o zaman:
        # → Tüm prompt’ları birleştirip AI’a verelim.

        full_prompt = "\n\n".join([p for p in prompts if p])
        return full_prompt

    except Exception as e:
        print(f"Google Sheets okuma hatası: {e}")
        return "Sen Yusuf'un Dijital Asistanısın. Kullanıcıya 'Merhaba!' de."

def get_gemini_response(user_message, full_prompt):
    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": (
                        f"Aşağıdaki kurallara göre kullanıcı mesajına cevap ver:\n\n"
                        f"KURALLAR:\n{full_prompt}\n\n"
                        f"Kullanıcının mesajı: \"{user_message}\"\n\n"
                        "Cevabın kısa, samimi ve 2-3 cümle olmalı. Doğrudan cevapla, açıklama yazma."
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
        response = r.json()
        return response['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Gemini hatası: {e}")
        return "Şu an size yardımcı olamıyorum. Lütfen 'stres evi', 'davet evi' veya 'proje' yazın."

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming_msg = request.form.get('Body', '').strip()
    print(f"Gelen mesaj: {incoming_msg}")

    full_prompt = find_matching_prompt(incoming_msg)
    reply = get_gemini_response(incoming_msg, full_prompt)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply}</Message>
</Response>""", 200, {'Content-Type': 'text/xml'}

@app.route('/')
def index():
    return "Yusuf'un WhatsApp Asistanı (Tek Sütun) çalışıyor ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
