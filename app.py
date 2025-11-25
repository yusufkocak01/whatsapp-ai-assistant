import os
import re
import logging
from flask import Flask, request, abort
import pandas as pd

# Optional OpenAI integration if you want fallback intelligent replies
try:
    import openai
except Exception:
    openai = None

# Twilio helper for replying via TwiML
from twilio.twiml.messaging_response import MessagingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp-assistant")

CSV_PATH = os.environ.get("PROMPT_CSV", "prompt.csv")  # değiştirilebilir via env
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")      # opsiyonel
# Twilio ile doğrudan TwiML döndüreceğimiz için REST client zorunlu değil

app = Flask(__name__)

def load_prompts(csv_path: str):
    """
    CSV must have columns: keyword, rules
    keyword can be a single word or multiple alternatives separated by '|' or ','.
    """
    if not os.path.exists(csv_path):
        logger.warning("prompt.csv bulunamadı: %s", csv_path)
        return pd.DataFrame(columns=["keyword", "rules"])
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    # Normalize columns
    if "keyword" not in df.columns or "rules" not in df.columns:
        raise ValueError("prompt.csv içinde 'keyword' ve 'rules' sütunları olmalı.")
    return df[["keyword", "rules"]]

def find_rule_for_text(text: str, df: pd.DataFrame):
    text_lower = text.lower()
    matches = []
    for _, row in df.iterrows():
        raw_keys = row["keyword"]
        # split alternatifleri , veya | ile ayır
        keys = re.split(r"\s*[|,]\s*", raw_keys) if raw_keys else []
        for k in keys:
            k = k.strip()
            if not k:
                continue
            # whole-word match (Türkçe'yi basitçe yakalamak için \b kullanıyoruz)
            pattern = r"\b" + re.escape(k.lower()) + r"\b"
            if re.search(pattern, text_lower, flags=re.UNICODE):
                matches.append((k, row["rules"]))
    # Örnek seçim: ilk eşleşme; daha sofistike mantık istersen burayı değiştirebiliriz.
    return matches[0][1] if matches else None

def ask_openai(prompt: str):
    """Opsiyonel: OPENAI_API_KEY varsa kısa bir cevap üretir."""
    if not OPENAI_API_KEY or openai is None:
        return None
    try:
        openai.api_key = OPENAI_API_KEY
        # Basit chat completion isteği (model adı organizasyonuna göre değişebilir)
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # hesabına göre uygun olanı koy
            messages=[{"role":"system","content":"Türkçe yardım asistanısın. Kısa ve nazik cevap ver."},
                      {"role":"user","content":prompt}],
            max_tokens=250,
            temperature=0.6
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("OpenAI çağrısında hata: %s", e)
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    # Twilio'dan form-data ile gelir, Body paramında mesaj vardır
    incoming = (request.values.get("Body") or "").strip()
    if not incoming:
        return ("", 204)

    logger.info("Gelen mesaj: %s", incoming)

    # Her istek için güncel CSV'yi oku (güncelleme kolaylığı için)
    try:
        df = load_prompts(CSV_PATH)
    except Exception as e:
        logger.exception("prompt.csv yüklenirken hata")
        resp = MessagingResponse()
        resp.message("Sunucuda prompt verisi yüklenemedi. Lütfen admin ile iletişime geçin.")
        return str(resp)

    matched_rule = find_rule_for_text(incoming, df)

    if matched_rule:
        # Eğer rules sütunu birden fazla alternatif içeriyorsa, olduğu gibi gönderiyoruz.
        reply = f"{matched_rule}\n\nBen dijital asistanınızım. Size nasıl yardımcı olabilirim? Lütfen ne yapmak istediğinizi kısaca yazın."
    else:
        # Eşleşme yoksa OpenAI ile try et (eğer varsa), yoksa basit fallback
        openai_reply = ask_openai(f"Kullanıcı mesajı: {incoming}\nKısa ve yardımcı bir cevap ver.")
        if openai_reply:
            reply = f"{openai_reply}\n\n(Ben dijital asistanınızım.)"
        else:
            reply = ("Merhaba — ben dijital asistanınızım. " 
                     "Mesajınızı tam anlayamadım. Kısaca ne yapmak istediğinizi açıklar mısınız? "
                     "Örn: 'randevu oluştur', 'fiyat bilgisi', 'bilgi: X' vb.")

    resp = MessagingResponse()
    resp.message(reply)
    logger.info("Gönderilen cevap: %s", reply)
    return str(resp)

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp Dijital Asistan webhooku çalışıyor."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
