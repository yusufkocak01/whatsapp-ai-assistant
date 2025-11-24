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

# !!!!! baslangic EN BAŞTA OLMALI !!!!!
TABS = ["baslangic", "stres_evi", "davet_evi", "sahibinden", "proje", "seslendirme", "metin", "mentor"]

def find_match_in_sheet(sheet_records, query):
    query = query.strip().lower()
    for row in sheet_records:
        keyword = str(row.get("ad", "")).strip().lower()
        if keyword and (keyword in query or query in keyword):
            return row
    return None

def get_tab_keywords(tab_name):
    """Bir sekmedeki tüm 'ad' değerlerini listeler (yardımcı öneri için)."""
    try:
        sheet = CLIENT.open_by_url(SHEET_URL).worksheet(tab_name)
        records = sheet.get_all_records()
        return [str(r.get("ad", "")) for r in records if r.get("ad")]
    except:
        return []

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    resp = MessagingResponse()
    msg = resp.message()

    matched_row = None
    matched_tab = None

    # Tüm sekmelerde eşleşme ara (baslangic hariç)
    for tab in TABS[1:]:  # baslangic hariç
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

    if matched_row:
        # Direkt eşleşme varsa, o satırın açıklamasını kullan
        desc = matched_row.get("açıklama", "Bilgi yok")
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}", "Content-Type": "application/json"},
                json={"model": "mistralai/mistral-7b-instruct:free", "messages": [{"role": "user", "content": f"Yalnızca şu bilgiyi günlük Türkçeyle aktar: {desc}"}], "max_tokens": 200}
            )
            reply = response.json().get("choices", [{}])[0].get("message", {}).get("content", desc)
        except:
            reply = desc
        msg.body(reply)

    else:
        # Hiçbir hizmet sekmesinde eşleşme yoksa → baslangic sekmesine bak
        try:
            sheet = CLIENT.open_by_url(SHEET_URL).worksheet("baslangic")
            records = sheet.get_all_records()
            match = find_match_in_sheet(records, incoming_msg)
            if match:
                reply = match.get("açıklama", "Merhaba! Size nasıl yardımcı olabilirim?")
                msg.body(reply)
            else:
                # Hiçbir şey eşleşmezse: genel yönlendirme
                msg.body(
                    "Merhaba! Ben Yusuf Koçak’ın dijital asistanıyım. 🌿\n\n"
                    "Size hangi konuda yardımcı olabilirim?\n"
                    "• Stres atmak\n• Davet evi\n• Proje yazımı\n• Kişiselleştirilmiş şarkı\n• Metin yazımı\n• Mentorluk\n• Sahibinden danışmanlık"
                )
        except:
            msg.body("Merhaba! Size nasıl yardımcı olabilirim?")

    return str(resp)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
