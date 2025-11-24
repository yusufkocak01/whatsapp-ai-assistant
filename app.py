from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import os

app = Flask(__name__)

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit"

# Tüm sekmeler
TABS = ["baslangic", "stres_evi", "davet_evi", "sahibinden", "proje", "seslendirme", "metin", "mentor"]

def find_match_in_sheet(sheet_records, query):
    query = query.strip().lower()
    for row in sheet_records:
        keyword = str(row.get("ANAHTAR KELİME", "")).strip().lower()
        if keyword and (keyword in query or query in keyword):
            return row.get("AÇIKLAMA (PROMPT)", "Anlaşıldı.")
    return None

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    resp = MessagingResponse()
    msg = resp.message()

    behavior_prompt = None

    # Tüm sekmelerde eşleşme ara
    for tab in TABS:
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab)
            records = sheet.get_all_records()
            prompt = find_match_in_sheet(records, incoming_msg)
            if prompt:
                behavior_prompt = prompt
                break
        except:
            continue

    if behavior_prompt:
        full_prompt = f"""
Sen Yusuf Koçak'ın dijital asistanısın. Adana'da hizmet veriyorsun.

Müşteri şunu yazdı: "{incoming_msg}"

Davranış talimatın:
"{behavior_prompt}"

Kurallar:
- Türkçe, samimi, günlük konuşma diliyle yanıt ver.
- Talimatta belirtilenleri MUTLAKA uygula.
- Satış yapmaya zorlama.
- Kısa ve net ol (1-3 cümle).
"""
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"},
                json={
                    "model": "mistralai/mistral-7b-instruct:free",
                    "messages": [{"role": "user", "content": full_prompt}],
                    "max_tokens": 300
                }
            )
            reply = response.json().get("choices", [{}])[0].get("message", {}).get("content", behavior_prompt[:200])
        except:
            reply = "Anlaşıldı. Detaylı bilgi için lütfen bizimle konuşun."
        msg.body(reply)
    else:
        msg.body("Merhaba! Detaylı bilgi almak için lütfen ne istediğini net şekilde yazabilir misin? 😊")

    return str(resp)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
