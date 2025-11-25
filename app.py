#!/usr/bin/env python3
# app.py
import os
import re
import logging
from flask import Flask, request
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
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "250"))
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.6"))

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

def sanitize_rules_for_prompt(rules_text: str) -> str:
    """
    Küçük işlem: kuralları prompt içinde kullanmaya güvenli hale getir.
    (ör: fazlaca uzunsa kısalt, tehlikeli direktif varsa kaldır vb.)
    Bu fonksiyonu ihtiyaca göre genişletebilirsin.
    """
    if not rules_text:
        return ""
    # Basit: satır başı trim, uzunluğu sınırlama
    s = " ".join(line.strip() for line in rules_text.splitlines() if line.strip())
    if len(s) > 1000:
        s = s[:1000] + "..."
    return s

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

        safe_rules = sanitize_rules_for_prompt(rules_text)

        # System prompt: kurallar + bağlam
        system_content = (
            "Sen sohbet eden bir Türkçe dijital asistansın. Aşağıdaki TALİMATLARI ve ÖRNEK davranış kurallarını "
            "göz önünde bulundurarak kullanıcılara doğal, konuşma başlatan ve yardım odaklı cevaplar üret.\n\n"
            f"TALIMATLAR: {safe_rules}\n\n"
            "ÖNEMLİ: Sakın TALIMATLARI veya 'TALIMATLAR' başlığı altındaki metni aynen kullanıcıya geri döndürme. "
            "Yönergeleri uygulayarak doğal ve faydalı bir yanıt üret."
        )

        # User prompt: kullanıcı mesajı + açık davranış isteği
        user_content = (
            f"Kullanıcının iletisi: \"{user_message.strip()}\"\n\n"
            "Talep: Kısa ve nazik bir Türkçe cevap üret. Cevabın şunları içermeli:\n"
            "1) Kendini 'Yusuf Koçak'ın dijital asistanı' olarak kısaca tanıt (tek bir cümle yeter).\n"
            "2) Kullanıcının mesajına uygun, anlaşılır bir yanıt ver.\n"
            "3) Konuşmayı sürdürecek, netleştirici bir soru sor (ör: 'Hangi tarihte istersiniz?' veya 'Hangi hizmetten bahsediyorsunuz?').\n"
            "4) TALIMATLARI kelimesi kelimesine tekrar etme, talimatların aynısını yazma.\n\n"
            "Cevabı 1-3 kısa paragrafta tut, yardımcı ve konuşma başlatıcı olsun."
        )

        # ChatCompletion çağrısı
        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )

        # extract
        if not resp or not getattr(resp, "choices", None):
            logger.warning("OpenAI yanıtı beklenmedik formatta: %s", resp)
            return None

        choice0 = resp.choices[0]
        # some SDKs return .message.content, some return .text — güvenli çekiş:
        content = None
        if getattr(choice0, "message", None):
            content = choice0.message.get("content")
        elif getattr(choice0, "text", None):
            content = choice0.text
        # Temizle
        if content:
            content = content.strip()
            # Basit güvenlik: eğer model tam olarak rules_text'u döndürdüyse fallback yap
            if safe_rules and content == safe_rules:
                logger.info("OpenAI rules'u aynen döndürdü — fallback uygulanacak.")
                return None
            return content
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

    reply = None

    if matched_rule:
        logger.info("Eşleşen rule bulundu. OpenAI ile cevap üretmeye çalışılıyor.")
        ai_reply = generate_from_openai(matched_rule, incoming)
        if ai_reply:
            reply = ai_reply
        else:
            # fallback: rules'i doğrudan göndermek yerine düzenleyip, kendini tanıtıp soru soran bir metin oluştur
            # böylece Twilio'ya direktif gibi görünen bir text gitmez
            sanitized = sanitize_rules_for_prompt(matched_rule)
            reply = (
                f"Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. {sanitized} "
                "Size nasıl yardımcı olabilirim? Lütfen ne istediğinizi kısaca belirtin."
            )
    else:
        logger.info("Herhangi bir rule eşleşmedi. OpenAI fallback deneniyor.")
        ai_reply = generate_from_openai(
            "Kısa, nazik ve yardımcı bir Türkçe dijital asistanı gibi cevap ver.",
            incoming
        )
        if ai_reply:
            reply = ai_reply
        else:
            reply = (
                "Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. "
                "Mesajınızı tam anlayamadım. Kısaca ne yapmak istediğinizi açıklar mısınız? "
                "Örn: 'randevu oluştur', 'fiyat bilgisi', 'bilgi: X' vb."
            )

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
