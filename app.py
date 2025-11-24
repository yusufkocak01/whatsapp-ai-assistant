import os
import json
import logging
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# -------------------- Ayarlar & Logger --------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_URL = os.environ.get("SHEET_URL") or "https://docs.google.com/spreadsheets/d/1WIrtBeUnrCSbwOcoaEFdOCksarcPva15XHN-eMhDrZc/edit"

# Sekme isimleri - Sheet'teki sayfa isimleri ile birebir eşleşmeli
TABS = ["baslangic", "stres_evi", "davet_evi", "sahibinden", "proje", "seslendirme", "metin", "mentor"]

# -------------------- Google Credentials yükleme --------------------
def load_gspread_client():
    """
    İki yol desteklenir:
    1) GOOGLE_CREDS_JSON env var'ı varsa onu parse edip kullan.
    2) credentials.json dosyası mevcutsa onu kullan.
    """
    creds_env = os.environ.get("GOOGLE_CREDS_JSON")
    try:
        if creds_env:
            logger.info("Using GOOGLE_CREDS_JSON from environment.")
            creds_dict = json.loads(creds_env)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        else:
            logger.info("Using local credentials.json file.")
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
        client = gspread.authorize(creds)
        # Test: open sheet to ensure valid
        # client.open_by_url(SHEET_URL)
        return client
    except Exception as e:
        logger.exception("Failed to create gspread client")
        raise

# Initialize gspread client once (will raise at startup if invalid)
try:
    CLIENT = load_gspread_client()
except Exception as e:
    CLIENT = None
    logger.error("Google client oluşturulamadı. GOOGLE_CREDS_JSON veya credentials.json kontrol et.")

# -------------------- Yardımcı fonksiyonlar --------------------
def find_match_row(sheet_records, query):
    """
    Daha esnek eşleşme:
    - 'anahtar kelime' hücresinde virgülle ayrılmış tokenlar desteklenir.
    - Her token küçük harfe çevrilip sorguda aranır.
    """
    if not query:
        return None
    q = query.strip().lower()
    for row in sheet_records:
        keyword_raw = row.get("anahtar kelime", "") or ""
        keyword = str(keyword_raw).strip().lower()
        if not keyword:
            continue
        # Eğer virgülle ayrılmış tokenlar varsa her birini kontrol et
        tokens = [t.strip() for t in keyword.split(",") if t.strip()]
        for token in tokens:
            if token in q:
                return row
        # fallback: eğer tam keyword metni sorgunun içinde geçiyorsa
        if keyword and keyword in q:
            return row
    return None

# -------------------- Webhook --------------------
@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    from_number = request.values.get('From', '')
    logger.info(f"Incoming message from {from_number}: {incoming_msg!r}")

    resp = MessagingResponse()
    msg = resp.message()

    if CLIENT is None:
        logger.error("GSpread client mevcut değil. GOOGLE_CREDS_JSON veya credentials.json yüklenmemiş olabilir.")
        msg.body("Sunucu yapılandırma hatası: veri kaynağına bağlanılamıyor. Lütfen yöneticiyi bilgilendir.")
        return str(resp)

    matched_row = None
    last_exception = None

    try:
        sh = CLIENT.open_by_url(SHEET_URL)
    except Exception as e:
        logger.exception("Failed to open spreadsheet by URL")
        msg.body("Sunucu hatası: Google Sheet'e erişilemiyor. Lütfen daha sonra tekrar deneyin.")
        return str(resp)

    # Tüm sekmeleri sırayla kontrol et
    for tab in TABS:
        try:
            logger.info(f"Trying worksheet/tab: {tab}")
            sheet = sh.worksheet(tab)
            records = sheet.get_all_records()
            logger.info(f"Tab '{tab}' - {len(records)} kayıt bulundu.")
            if records:
                # Log headerları kontrol etmek faydalı olur
                headers = records[0].keys() if len(records) > 0 else []
                logger.debug(f"Tab '{tab}' headers: {list(headers)}")
            row = find_match_row(records, incoming_msg)
            if row:
                matched_row = row
                logger.info(f"Matched row in tab '{tab}': {row}")
                break
        except Exception as e:
            logger.exception(f"Error reading tab {tab}")
            last_exception = e
            continue

    # Eşleşme bulunduysa OpenRouter'a gönder veya direkt açıklamayı kullan
    if matched_row:
        keyword = matched_row.get("anahtar kelime", "").strip()
        prompt_text = matched_row.get("aciklama", "").strip() or "Anlaşıldı. Size nasıl yardımcı olabilirim?"
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
        # OpenRouter çağrısı
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if openrouter_key:
            try:
                logger.info("Sending request to OpenRouter")
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openrouter_key}"},
                    json={
                        "model": "mistralai/mistral-7b-instruct:free",
                        "messages": [{"role": "user", "content": full_prompt}],
                        "max_tokens": 300,
                    },
                    timeout=15
                )
                response.raise_for_status()
                data = response.json()
                logger.debug(f"OpenRouter raw response: {data}")
                choices = data.get("choices") or []
                content = None
                if isinstance(choices, list) and len(choices) > 0:
                    # güvenli çekme
                    first = choices[0]
                    if isinstance(first, dict):
                        # yeni formatlarda message.content olabilir
                        content = first.get("message", {}).get("content") or first.get("text") or first.get("message")
                reply = content or (prompt_text[:300] if prompt_text else "Anlaşıldı. Detaylı bilgi için lütfen bizimle konuşun.")
            except Exception as e:
                logger.exception("OpenRouter çağrısında hata")
                reply = prompt_text[:300] if prompt_text else "Anlaşıldı. Detaylı bilgi için lütfen bizimle konuşun."
        else:
            logger.warning("OPENROUTER_API_KEY bulunamadı; OpenRouter kullanılmayacak. Direkt prompt_text döndürülüyor.")
            reply = prompt_text[:300] if prompt_text else "Anlaşıldı. Detaylı bilgi için lütfen bizimle konuşun."

        msg.body(reply)
    else:
        logger.info(f"No matched row found. last_exception: {last_exception}")
        msg.body("Merhaba! Detaylı bilgi almak için lütfen ne istediğini net şekilde yazabilir misin? 😊")

    return str(resp)

# -------------------- Local run --------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    host = "0.0.0.0"
    logger.info(f"Starting app on {host}:{port}")
    app.run(host=host, port=port)
