#!/usr/bin/env python3
# app.py
import os
import re
import logging
from flask import Flask, request
import pandas as pd
import difflib

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
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.45"))
# similarity threshold (0..1) above which we consider model to be "echoing" the rules
ECHO_SIMILARITY_THRESHOLD = float(os.environ.get("ECHO_SIMILARITY_THRESHOLD", "0.45"))

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
        raw_keys = row["keyword"] or ""
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
    if not rules_text:
        return ""
    s = " ".join(line.strip() for line in rules_text.splitlines() if line.strip())
    if len(s) > 1200:
        s = s[:1200] + "..."
    return s

def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()

def pick_followup_question_from_rules(rules_text: str):
    """
    Basit heuristic: rules içinde geçen anahtar kelimelere göre soru üret.
    Eğer bir şey bulunamazsa genel bir konuşma açıcı soru döndürür.
    """
    rt = rules_text.lower()
    if any(k in rt for k in ["randevu", "randevu oluştur", "tarih", "saat"]):
        return "Hangi tarih ve saat için randevu istiyorsunuz?"
    if any(k in rt for k in ["fiyat", "ücret", "ücretlendirme", "fiyat bilgisi"]):
        return "Hangi hizmet için fiyat almak istiyorsunuz? (örn: palyaço, mehter)"
    if any(k in rt for k in ["iletişim", "telefon", "mail"]):
        return "İletişim bilgisi mi istiyorsunuz? Telefon veya e-posta hangisini tercih edersiniz?"
    if any(k in rt for k in ["bilgi", "detay", "açıklama"]):
        return "Hangi konuda detay istiyorsunuz?"
    # fallback
    return "Size nasıl yardımcı olabilirim? Hangi konuda destek istersiniz?"

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

        # System prompt: daha güçlü şekilde "do not echo" talimatı
        system_content = (
            "You are a Turkish-language conversational assistant. "
            "Follow the instructions below to craft a natural, helpful reply. "
            "DO NOT repeat or echo the instructions themselves to the user. "
            "If the instruction contains meta-language (e.g., 'Sen de aynı türden cevap yaz'), "
            "use it to shape behavior but do NOT include that sentence in your reply."
            "\n\nINSTRUCTIONS: " + safe_rules
        )

        # User content: kullanıcı mesajı + açık format talepleri
        user_content = (
            f"Kullanıcının iletisi: \"{user_message.strip()}\"\n\n"
            "Talep: Türkçe, kısa ve nazik bir cevap üret. Cevap şunları içermeli:\n"
            "1) Kendini bir cümlede 'Yusuf Koçak'ın dijital asistanı' olarak tanıt.\n"
            "2) Kullanıcının mesajıyla ilgili doğal bir yanıt ver.\n"
            "3) Konuşmayı sürdürecek açık bir soru sorarak ne istediğini netleştir (örnek sorular kullanabilirsin).\n"
            "NOT: Talimat metnini aynen tekrar etme. Sadece sonucu ver."
        )

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
        content = None
        if getattr(choice0, "message", None):
            content = choice0.message.get("content")
        elif getattr(choice0, "text", None):
            content = choice0.text

        if not content:
            return None

        content = content.strip()

        # Kontrol: model rules'u direkt ya da çok benzer şekilde döndürdü mü?
        sim = similarity(content, safe_rules)
        logger.info("OpenAI returned content similarity to rules: %.3f", sim)
        if sim >= ECHO_SIMILARITY_THRESHOLD or safe_rules in content:
            logger.info("Detected likely echoing of rules (sim >= %.3f). Returning None to trigger fallback.", ECHO_SIMILARITY_THRESHOLD)
            return None

        # Ayrıca, eğer cevap açıkça talimat içeriğini tekrarlıyorsa (örn 'Sen de aynı türden cevap yaz...'), reddet
        lowerc = content.lower()
        if "sen de aynı türden" in lowerc or "talimat" in lowerc or "yönerge" in lowerc:
            logger.info("Detected forbidden phrase in response; treating as echo.")
            return None

        return content
    except Exception as e:
        logger.exception("OpenAI çağrısı sırasında hata: %s", e)
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming = (request.values.get("Body") or "").strip()
    if not incoming:
        return ("", 204)

    logger.info("Gelen mesaj: %s", incoming[:1000])

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
            logger.info("OpenAI cevabı kullanılıyor.")
            reply = ai_reply
        else:
            # fallback: doğrudan talimatı tekrar etmeyecek şekilde cevap hazırla
            logger.info("OpenAI yok veya echo tespit edildi. Fallback uygulanıyor.")
            question = pick_followup_question_from_rules(matched_rule)
            reply = f"Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. {question}"
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
    logger.info("Gönderilen cevap (ilk 300 char): %s", reply[:300])
    return str(resp)

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp Dijital Asistan webhooku çalışıyor."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
