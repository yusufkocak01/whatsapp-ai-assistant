from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import os
import re

app = Flask(__name__)

# Google Sheets erişimi
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit"

# Tüm sekme isimleri
TABS = ["stres_evi", "davet_evi", "sahibinden", "proje", "seslendirme", "metin", "mentor"]

def find_best_match(user_query, sheet_records):
    """Kullanıcının sorduğuyla en uygun 'ad' sütununu bulur."""
    user_query = user_query.lower().strip()
    best_match = None
    best_score = 0

    for row in sheet_records:
        keyword = str(row.get("ad", "")).lower()
        if not keyword:
            continue
        # Basit eşleşme: kelime içeriyorsa
        if keyword in user_query or user_query in keyword:
            score = len(set(user_query.split()) & set(keyword.split()))
            if score > best_score:
                best_score = score
                best_match = row
    return best_match

def get_all_tab_keywords():
    """Tüm sekmelerdeki 'ad' sütunlarını listeler (yardımcı öneri için)."""
    keywords = {}
    for tab in TABS:
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab)
            records = sheet.get_all_records()
            kw_list = [str(r.get("ad", "")) for r in records if r.get("ad")]
            if kw_list:
                keywords[tab] = kw_list
        except:
            continue
    return keywords

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    resp = MessagingResponse()
    msg = resp.message()

    # 1. Önce tüm sekmelerde doğrudan eşleşme ara
    matched_row = None
    matched_tab = None

    for tab in TABS:
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab)
            records = sheet.get_all_records()
            match = find_best_match(incoming_msg, records)
            if match:
                matched_row = match
                matched_tab = tab
                break
        except:
            continue

    if matched_row:
        # 2. Eşleşme bulunduysa, o satırdaki tüm verileri kullan
        context = f"""
Hizmet: {matched_tab}
Soru: {matched_row.get('ad', '')}
Açıklama: {matched_row.get('açıklama', 'Bilgi yok')}
Fiyat: {matched_row.get('fiyat', 'Belirtilmemiş')}
Süre: {matched_row.get('süre', 'Belirtilmemiş')}
Notlar: {matched_row.get('notlar', '')}
        """.strip()

        prompt = f"""
Sen Yusuf Koçak'ın dijital asistanısın. Aşağıdaki bilgileri kullanarak müşteriye yardımcı ol.
SADECE bu bilgileri kullan — dış bilgi ekleme, uydurma, tahmin etme.

{context}

Kurallar:
- Samimi, günlük Türkçe konuşma diliyle yanıt ver.
- Kısa ve net ol.
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
                    "max_tokens": 400
                }
            )
            reply = response.json().get("choices", [{}])[0].get("message", {}).get("content", "Şu an yardımcı olamıyorum.")
        except:
            reply = matched_row.get("açıklama", "Bilgi alınamadı.")  # Fallback: direkt açıklama
        msg.body(reply)

    else:
        # 3. Hiçbir eşleşme yoksa: hangi hizmet olduğunu sor
        msg.body(
            "Merhaba! Size nasıl yardımcı olabilirim?\n\n"
            "Hangi hizmetle ilgileniyorsunuz?\n"
            "• Stres atmak\n• Davet evi\n• Proje yazımı\n• Kişiselleştirilmiş şarkı\n• Metin yazımı\n• Mentorluk\n• Sahibinden danışmanlık"
        )

    return str(resp)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
