from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import os

app = Flask(__name__)

# Google Sheets'e erişim
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit"

def get_data_from_sheet(tab_name):
    try:
        sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab_name)
        records = sheet.get_all_records()
        text = "\n".join([f"- {r['ad']} ({r['fiyat']} TL): {r['açıklama']}" for r in records])
        return text
    except:
        return "Bu kategori için bilgi bulunamadı."

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip().lower()
    resp = MessagingResponse()
    msg = resp.message()

    # Basit anahtar kelime algılama
    if "stres" in incoming_msg:
        tab = "stres_evi"
    elif "davet" in incoming_msg:
        tab = "davet_evi"
    elif "şarkı" in incoming_msg or "ses" in incoming_msg:
        tab = "seslendirme"
    elif "proje" in incoming_msg:
        tab = "proje"
    elif "metin" in incoming_msg:
        tab = "metin"
    elif "mentor" in incoming_msg:
        tab = "mentor"
    elif "sahibinden" in incoming_msg:
        tab = "sahibinden"
    else:
        tab = "stres_evi"  # Varsayılan

    sheet_data = get_data_from_sheet(tab)

    # OpenRouter API çağrısı
    prompt = f"""
Sen Yusuf Koçak'ın dijital asistanısın. Adana merkezli hizmet veriyorsun.
Müşteri: "{incoming_msg}"
Hizmet verileri:
{sheet_data}

Yanıtla:
- Samimi, empatik, danışman bir dille
- "Duygunu Boşalt, Sakin Çık" felsefesini yansıt
- Satış yapmaya zorlama
- Türkçe ve doğal konuşma diliyle
"""
    try:
        openrouter_resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mistralai/mistral-7b-instruct:free",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500
            }
        )
        reply = openrouter_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "Şu an yardımcı olamıyorum.")
    except Exception as e:
        reply = "Teknik bir hata oluştu. Lütfen daha sonra tekrar deneyin."

    msg.body(reply)
    return str(resp)

if __name__ == '__main__':
    app.run()