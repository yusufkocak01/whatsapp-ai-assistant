import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

app = Flask(__name__)

# Google Sheets bağlantısı — credentials.json doğrudan okunur
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit"

# Tüm sekme isimleri
TABS = ["baslangic", "stres_evi", "davet_evi", "sahibinden", "proje", "seslendirme", "metin", "mentor"]

def find_match_row(sheet_records, query):
    query = query.strip().lower()
    for row in sheet_records:
        keyword = str(row.get("anahtar kelime", "")).strip().lower()
        if keyword and (keyword in query or query in keyword):
            return row
    return None

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    resp = MessagingResponse()
    msg = resp.message()

    matched_row = None

    for tab in TABS:
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab)
            records = sheet.get_all_records()
            row = find_match_row(records, incoming_msg)
            if row:
                matched_row = row
                break
        except Exception:
            continue

    if matched_row:
        keyword = matched_row.get("anahtar kelime", "").strip()
        prompt_text = matched_row.get("aciklama", "").strip()
        
        full_prompt = f"""
Sen Yusuf Koçak'ın dijital asistanısın. Adana'da hizmet veriyorsun.
Müşteri şunu yazdı: "{incoming_msg}"

Bu sorgu, şu anahtar kelimeye eşleşti: "{keyword}"
Davranış talimatın:
"{prompt_text}"

Kurallar:
- Eğer talimatta net bir talimat varsa (örneğin "önce kişi sayısını sor"), bunu kesinlikle yerine getir.
- Aksi takdirde, samimi, günlük Türkçe konuşma diliyle doğal bir yanıt ver.
- Satış yapmaya zorlama.
- Yanıt 1-3 cümle arası olsun.
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
            reply = response.json().get("choices", [{}])[0].get("message", {}).get("content", prompt_text[:150] or "Anlaşıldı.")
        except Exception:
            reply = "Anlaşıldı. Detaylı bilgi için lütfen bizimle konuşun."
        msg.body(reply)
    else:
        msg.body("Merhaba! Detaylı bilgi almak için lütfen ne istediğini net şekilde yazabilir misin? 😊")

    return str(resp)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
