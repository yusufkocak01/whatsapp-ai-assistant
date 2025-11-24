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

# Tüm sekmeler — sırayla taranacak
TABS = ["baslangic", "stres_evi", "davet_evi", "sahibinden", "proje", "seslendirme", "metin", "mentor"]

def find_match_in_sheet(sheet_records, query):
    """Kullanıcı sorgusunu 'anahtar kelime' sütununda arar (case-insensitive)."""
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
    matched_tab = None

    # Önce spesifik sekmelerde (baslangic hariç) ara
    for tab in TABS[1:]:
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab)
            records = sheet.get_all_records()
            match = find_match_in_sheet(records, incoming_msg)
            if match:
                matched_row = match
                matched_tab = tab
                break
        except:
            continue

    # Eğer spesifik sekmede eşleşme yoksa, baslangic sekmesine bak
    if not matched_row:
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet("baslangic")
            records = sheet.get_all_records()
            match = find_match_in_sheet(records, incoming_msg)
            if match:
                matched_row = match
                matched_tab = "baslangic"
        except:
            pass

    if matched_row:
        # Açıklama zorunlu — diğerleri opsiyonel
        desc = str(matched_row.get("açıklama", "Bilgi mevcut değil."))
        price = matched_row.get("fiyat", "Belirtilmemiş")
        duration = matched_row.get("süre", "Belirtilmemiş")
        notes = matched_row.get("notlar", "")

        # Bağlamı oluştur
        context_parts = [f"Ana bilgi: {desc}"]
        if price not in ["-", "Belirtilmemiş", ""]:
            context_parts.append(f"Fiyat: {price}")
        if duration not in ["-", "Belirtilmemiş", ""]:
            context_parts.append(f"Süre: {duration}")
        if notes and notes != "-":
            context_parts.append(f"Ek not: {notes}")

        full_context = "\n".join(context_parts)

        # Yapay zekaya sadece bu bilgileri kullanmasını söyle
        prompt = f"""
Sen Yusuf Koçak'ın dijital asistanısın. Aşağıdaki bilgileri kullanarak müşteriye kısa ve net yardımcı ol.
SADECE aşağıdaki bilgileri kullan — dış bilgi ekleme, uydurma, tahmin etme.

{full_context}

Kurallar:
- Günlük, samimi Türkçe kullan.
- 1-2 cümlede yanıt ver.
- Satış yapma, sadece bilgi ver.
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
                    "max_tokens": 250
                }
            )
            reply = response.json().get("choices", [{}])[0].get("message", {}).get("content", desc)
        except:
            reply = desc  # OpenRouter hatasında direkt açıklama kullan
        msg.body(reply)

    else:
        # Hiçbir eşleşme yoksa: çok kısa, nötr yanıt
        msg.body("Merhaba! Detaylı bilgi almak için lütfen ne istediğini net şekilde yazabilir misin? 😊")

    return str(resp)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
