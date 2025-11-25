import os
import re
import logging
from flask import Flask, request, abort
import pandas as pd

# OpenAI (opsiyonel ama bu versiyon OpenAI ile rules -> cevap üretir)
try:
    import openai
except Exception:
    openai = None

from twilio.twiml.messaging_response import MessagingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp-assistant")

CSV_PATH = os.environ.get("PROMPT_CSV", "prompt.csv")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
# model is configurable via env, default to a capable chat model name you have access to
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

app = Flask(__name__)

def load_prompts(csv_path: str):
    if not os.path.exists(csv_path):
        logger.warning("prompt.csv bulunamadı: %s", csv_path)
        return pd.DataFrame(columns=["keyword", "rules"])
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    if "keyword" not in df.columns or "rules" not in df.columns:
        raise ValueError("prompt.csv içinde 'keyword' ve 'rules' sütunları olmalı.")
    return df[["keyword", "rules"]]

def find_rule_for_text(text: str, df: pd.DataFrame):
    text_lower = text.lower()
    for _, row in df.iterrows():
        raw_keys = row["keyword"]
        keys = re.split(r"\s*[|,]\s*", raw_keys) if raw_keys else []
        for k in keys:
            k = k.strip()
            if not k:
                continue
            pattern = r"\b" + re.escape(k.lower()) + r"\b"
            if re.search(pattern, text_lower, flags=re.UNICODE):
                return row["rules"]
    return None

def generate_from_openai(rules_text: str, user_message: str):
    """
    rules_text: prompt template from CSV (instructions for the assistant)
    user_message: the incoming user's raw message
    Returns generated reply string on success, otherwise None.
    """
    if not OPENAI_API_KEY or openai is None:
        logger.debug("OpenAI konfigürasyon yok veya paket yüklü değil.")
        return None

    try:
        openai.api_key = OPENAI_API_KEY

        # Build messages: use rules_text as system/instruction and include the user's message
        messages = [
            {"role": "system", "content": f"{rules_text.strip()}"},
            {"role": "user", "content": f"Kullanıcının mesajı: \"{user_message.strip()}\"\n\nKısa, nazik ve konuşma başlatıcı bir Türkçe cevap üret. Kendini 'Yusuf Koçak'ın dijital asistanı' olarak tanıt ve kullanıcıdan ne istediğini anlamaya yönelik bir açık soru sor."}
        ]

        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=250,
            temperature=0.7
        )
        # Safely extract content
        content = resp.choices[0].message.get("content") if resp.choices and resp.choices[0].message else None
        if content:
            return content.strip()
        return None
    except Exception as e:
        logger.exception("OpenAI çağrısı sırasında hata: %s", e)
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming = (request.values.get("Body") or "").strip()
    if not incoming:
        return ("", 204)

    logger.info("Gelen mesaj: %s", incoming)

    try:
        df = load_prompts(CSV_PATH)
    except Exception as e:
        logger.exception("prompt.csv yüklenirken hata")
        resp = MessagingResponse()
        resp.message("Sunucuda prompt verisi yüklenemedi. Lütfen admin ile iletişime geçin.")
        return str(resp)

    matched_rule = find_rule_for_text(incoming, df)

    if matched_rule:
        # Eğer rules alanı varsa, onu OpenAI'ye prompt olarak yollamaya çalış
        openai_reply = generate_from_openai(matched_rule, incoming)
        if openai_reply:
            reply = openai_reply
        else:
            # Fallback: direkt rules içeriğini düzenleyip gönder
            # Eğer rules içinde doğrudan "sen ..." şeklinde yönlendirme varsa kullanıcının anlayacağı biçime çevir
            reply = f"{matched_rule}\n\nBen Yusuf Koçak'ın dijital asistanıyım. Size nasıl yardımcı olabilirim? Lütfen ne istediğinizi kısaca yazın."
    else:
        # Eşleşme yoksa yine OpenAI fallback deneyebiliriz
        openai_reply = generate_from_openai("Kısa, nazik ve yardımcı bir Türkçe dijital asistanı gibi cevap ver.", incoming)
        if openai_reply:
            reply = openai_reply
        else:
            reply = ("Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. "
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
