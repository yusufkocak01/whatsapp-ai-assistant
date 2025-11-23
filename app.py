from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import os

app = Flask(__name__)

# Google Sheets erişimi
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit"

# Hizmet sekmeleri
TABS = ["stres_evi", "davet_evi", "sahibinden", "proje", "seslendirme", "metin", "mentor"]

def find_match_in_sheet(sheet_records, query):
    """Kullanıcı sorgusunu 'ad' sütununda arar (alt/üst harf duyarsız)."""
    query = query.strip().lower()
    for row in sheet_records:
        keyword = str(row.get("ad", "")).strip().lower()
        if keyword and (keyword in query or query in keyword):
            return row
    return None

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    resp = MessagingResponse()
    msg = resp.message()

    matched_row = None
    matched_tab = None

    # Tüm sekmelerde eşleşme ara
    for tab in TABS:
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab)
            records = sheet.get_all_records()
            match = find_match_in_sheet(records, incoming_msg)
            if match:
                matched_row = match
                matched_tab = tab
                break
        except Exception as e:
            continue  # Sekme yoksa geç

    if matched_row:
        # Satırdaki tüm bilgileri topla
        desc = matched_row.get("açıklama", "Bilgi yok")
        price = matched_row.get("fiyat", "Belirtilmemiş")
        duration = matched_row.get("süre", "Belirtilmemiş")
        notes = matched_row.get("notlar", "")

        # Yapay zekaya gönderilecek bağlam
        context_lines = [f"Açıklama: {desc}"]
        if price != "Belirtilmemiş" and price != "-":
            context_lines.append(f"Fiyat: {price}")
        if duration != "Belirtilmemiş" and duration != "-":
            context_lines.append(f"Süre: {duration}")
        if notes:
            context_lines.append(f"Notlar: {notes}")

        full_context = "\n".join(context_lines)

        prompt = f"""
Sen Yusuf Koçak'ın dijital asistanısın. Aşağıdaki bilgileri kullanarak müşteriye yardımcı ol.
SADECE bu bilgileri kullan — dış bilgi ekleme, uydurma, tahmin etme.

{full_context}

Kurallar:
- Samimi, günlük Türkçe konuşma diliyle yanıt ver.
- Kısa ve net ol (maksimum 2-3 cümle).
- Satış yapmaya zorlama; sadece bilgi ver.
- Eğer açıklama yetersizse, "Detaylı bilgi için lütfen bizimle konuşun." de.
"""

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "mistralai/mistral-7b-instruct:free",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300
                }
            )
            reply = response.json().get("choices", [{}])[0].get("message", {}).get("content", desc)
        except:
            reply = desc  # OpenRouter hatasında direkt açıklama kullan
        msg.body(reply)

    else:
        # Hiçbir eşleşme yoksa yönlendir
        msg.body(
            "Merhaba! Size nasıl yardımcı olabilirim?\n\n"
            "Hangi hizmetle ilgileniyorsunuz?\n"
            "• Stres atmak\n• Davet evi\n• Proje yazımı\n• Kişiselleştirilmiş şarkı\n• Metin yazımı\n• Mentorluk\n• Sahibinden danışmanlık"
        )

    return str(resp)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
