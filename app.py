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
        # Sadece "açıklama" sütunlarını al, her satırı bir satırda topla
        descriptions = [str(r.get("açıklama", "")).strip() for r in records if r.get("açıklama")]
        return "\n".join(descriptions) if descriptions else "Bu hizmetle ilgili bilgi mevcut değil."
    except Exception as e:
        return "Bu hizmetle ilgili bilgi mevcut değil."

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip().lower()
    resp = MessagingResponse()
    msg = resp.message()

    # Basit anahtar kelimeye göre sekme seçimi
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

    # OpenRouter API çağrısı — açıklama metnini temel al, ama doğal yanıt üret
    prompt = f"""
Sen Yusuf Koçak'ın dijital asistanısın. Adana'da hizmet veriyorsun.
Müşteri şu soruyu sordu: "{incoming_msg}"

Aşağıda, ilgili hizmetle ilgili resmi açıklama yer alıyor.  
Bu açıklamayı mutlaka temel al, ama cevabını kendi doğal dilinle, samimi ve empatik bir şekilde oluştur:

"{sheet_data}"

Kurallar:
- Satış yapmaya zorlama
- Türkçe, günlük konuşma diliyle yaz
- Müşterinin duygusal ihtiyacını anla ve ona göre ilerle
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
