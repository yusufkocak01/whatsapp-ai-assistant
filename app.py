#!/usr/bin/env python3
# app.py
"""
WhatsApp dijital asistan webhooku (Twilio uyumlu).
Özellikler:
- prompt.csv (keyword, rules) okur
- gelen mesajdaki keyword'e göre rules metnini OpenAI'ye prompt olarak verir
- OpenAI cevabını echo (rules'un aynen dönmesini) kontrol ederek gerekirse fallback uygular
- Handoff mekanizması: admin numaraları BOT OFF / BOT ON ile botu devre dışı / aktif edebilir
- Eğer OpenAI yoksa güvenli fallback gönderir
- Twilio MessagingResponse ile TwiML döner
"""
import os
import re
import time
import logging
import difflib
from typing import Dict

from flask import Flask, request
import pandas as pd

# optional openai import
try:
    import openai
except Exception:
    openai = None

from twilio.twiml.messaging_response import MessagingResponse

# ---------- Config ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp-assistant")

CSV_PATH = os.environ.get("PROMPT_CSV", "prompt.csv")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # optional, required for OpenAI usage
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "250"))
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.45"))
ECHO_SIMILARITY_THRESHOLD = float(os.environ.get("ECHO_SIMILARITY_THRESHOLD", "0.45"))

# ADMIN_NUMBERS default as requested. You may override by setting the env var ADMIN_NUMBERS.
# Expected format examples: "whatsapp:+905322034617,whatsapp:+905551112233"
_default_admins = "whatsapp:+905322034617"
ADMIN_NUMBERS = set(
    n.strip() for n in os.environ.get("ADMIN_NUMBERS", _default_admins).split(",") if n.strip()
)

# Handoff TTL in seconds (optional). If >0, handoff will auto-resume after TTL seconds.
HANDOFF_TTL = int(os.environ.get("HANDOFF_TTL_SECONDS", str(60 * 60)))  # default 1 hour

# In-memory handoff state (key = sender phone string)
HANDOFF_STATE: Dict[str, dict] = {}

app = Flask(__name__)

# ---------- Helper functions ----------

def load_prompts(csv_path: str):
    """
    Load prompt.csv with columns: keyword, rules
    """
    if not os.path.exists(csv_path):
        logger.warning("prompt.csv bulunamadı: %s", csv_path)
        return pd.DataFrame(columns=["keyword", "rules"])
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    if "keyword" not in df.columns or "rules" not in df.columns:
        raise ValueError("prompt.csv içinde 'keyword' ve 'rules' sütunları olmalı.")
    return df[["keyword", "rules"]]

def find_rule_for_text(text: str, df: pd.DataFrame):
    """
    Find the first matching rule for the incoming text using whole-word matching.
    Keys in 'keyword' can be separated by ',' or '|'.
    """
    text_lower = (text or "").lower()
    for _, row in df.iterrows():
        raw_keys = row.get("keyword", "") or ""
        keys = re.split(r"\s*[|,]\s*", raw_keys) if raw_keys else []
        for k in keys:
            k = k.strip()
            if not k:
                continue
            # whole-word boundary match
            pattern = r"\b" + re.escape(k.lower()) + r"\b"
            if re.search(pattern, text_lower, flags=re.UNICODE):
                return row.get("rules", "")
    return None

def sanitize_rules_for_prompt(rules_text: str) -> str:
    """
    Make rules safe/compact to place into a system prompt.
    """
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
    Heuristic follow-up question generation based on keywords inside rules_text.
    """
    rt = (rules_text or "").lower()
    if any(k in rt for k in ["randevu", "randevu oluştur", "tarih", "saat"]):
        return "Hangi tarih ve saat için randevu istiyorsunuz?"
    if any(k in rt for k in ["fiyat", "ücret", "ücretlendirme", "fiyat bilgisi"]):
        return "Hangi hizmet için fiyat almak istiyorsunuz? (örn: palyaço, mehter)"
    if any(k in rt for k in ["iletişim", "telefon", "mail", "e-posta"]):
        return "İletişim bilgisi mi istiyorsunuz? Telefon ya da e-posta hangisini tercih edersiniz?"
    if any(k in rt for k in ["bilgi", "detay", "açıklama"]):
        return "Hangi konuda detay istiyorsunuz?"
    return "Size nasıl yardımcı olabilirim? Hangi konuda destek istersiniz?"

def generate_from_openai(rules_text: str, user_message: str):
    """
    Use OpenAI to generate a reply based on rules_text as an instruction.
    Returns generated reply or None if failed or echo detected.
    """
    if not OPENAI_API_KEY or openai is None:
        logger.debug("OpenAI konfigürasyon yok veya paket yüklenmemiş.")
        return None

    try:
        openai.api_key = OPENAI_API_KEY
        safe_rules = sanitize_rules_for_prompt(rules_text)

        system_content = (
            "You are a Turkish conversational assistant. Follow the instructions below to produce a "
            "natural, helpful reply. DO NOT repeat or echo the instruction text verbatim to the user. "
            "Use the instruction to shape behavior but do not output the instruction itself.\n\n"
            "INSTRUCTIONS: " + safe_rules
        )

        user_content = (
            f"Kullanıcının mesajı: \"{user_message.strip()}\"\n\n"
            "Talep: Kısa, nazik ve konuşma başlatıcı bir Türkçe cevap üret. "
            "Cevabında:\n"
            "1) Kendini bir cümlede 'Yusuf Koçak'ın dijital asistanı' olarak tanıt.\n"
            "2) Kullanıcının mesajına uygun doğal bir yanıt ver.\n"
            "3) Konuşmayı sürdürecek, netleştirici bir soru sor.\n"
            "NOT: Talimat metnini aynen tekrar etme."
        )

        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )

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

        # Check for echo: similarity with rules or direct inclusion
        sim = similarity(content, safe_rules)
        logger.info("OpenAI content similarity to rules: %.3f", sim)
        if sim >= ECHO_SIMILARITY_THRESHOLD or safe_rules in content:
            logger.info("Detected likely echoing of rules (sim >= %.3f).", ECHO_SIMILARITY_THRESHOLD)
            return None

        # Avoid some obvious forbidden phrases that indicate echo
        lowerc = content.lower()
        if "sen de aynı türden" in lowerc or "talimat" in lowerc or "yönerge" in lowerc:
            logger.info("Detected forbidden phrase in response; treating as echo.")
            return None

        return content
    except Exception as e:
        logger.exception("OpenAI çağrısı sırasında hata: %s", e)
        return None

# ---------- Handoff helpers ----------

def normalize_sender(s: str) -> str:
    """
    Normalize Twilio 'From' format. Usually Twilio gives 'whatsapp:+905...' — keep as is.
    If other formats expected, extend here.
    """
    return (s or "").strip()

def is_admin(sender: str) -> bool:
    return sender in ADMIN_NUMBERS

def set_handoff(sender: str, by: str = "admin"):
    HANDOFF_STATE[sender] = {"handed_off": True, "by": by, "since": time.time()}

def clear_handoff(sender: str):
    HANDOFF_STATE.pop(sender, None)

def check_handoff_active(sender: str) -> bool:
    state = HANDOFF_STATE.get(sender)
    if not state:
        return False
    if HANDOFF_TTL and time.time() - state.get("since", 0) > HANDOFF_TTL:
        # expire
        HANDOFF_STATE.pop(sender, None)
        return False
    return True

# ---------- Routes ----------

@app.route("/webhook", methods=["POST"])
def webhook():
    # Get message and sender
    incoming = (request.values.get("Body") or "").strip()
    sender_raw = (request.values.get("From") or request.values.get("from") or "").strip()
    sender = normalize_sender(sender_raw)

    if not incoming:
        return ("", 204)

    logger.info("Gelen mesaj (sender=%s): %s", sender, incoming[:1000])

    # Load prompts
    try:
        df = load_prompts(CSV_PATH)
    except Exception as e:
        logger.exception("prompt.csv yüklenirken hata")
        resp = MessagingResponse()
        resp.message("Sunucuda prompt verisi yüklenemedi. Lütfen admin ile iletişime geçin.")
        return str(resp)

    # --- Admin commands (only from ADMIN_NUMBERS) ---
    cmd = incoming.strip().lower()
    if is_admin(sender):
        if cmd in ("bot off", "stop bot", "bot kapat", "bot:off"):
            set_handoff(sender, by="admin")
            resp = MessagingResponse()
            resp.message("Bot devre dışı bırakıldı. Artık gelen mesajlara otomatik cevap gönderilmeyecek.")
            logger.info("Admin %s set BOT OFF for sender %s", sender, sender)
            return str(resp)
        if cmd in ("bot on", "start bot", "bot aç", "bot:on"):
            clear_handoff(sender)
            resp = MessagingResponse()
            resp.message("Bot tekrar aktif edildi.")
            logger.info("Admin %s set BOT ON for sender %s", sender, sender)
            return str(resp)

    # --- If handoff active for this sender, do not send bot replies ---
    if check_handoff_active(sender):
        logger.info("Handoff aktif - bot cevap üretmiyor for sender %s", sender)
        # Optionally, you could forward message to operator or log it for later.
        # Return 204 or empty TwiML to acknowledge webhook.
        return ("", 204)

    # --- Normal bot processing ---
    matched_rule = find_rule_for_text(incoming, df)
    reply = None

    if matched_rule:
        logger.info("Eşleşen rule bulundu - OpenAI ile cevap üretilecek.")
        ai_reply = generate_from_openai(matched_rule, incoming)
        if ai_reply:
            reply = ai_reply
            logger.info("OpenAI cevabı kullanılacak (len=%d).", len(reply))
        else:
            logger.info("OpenAI yok veya echo tespit edildi -> fallback kullanılıyor.")
            question = pick_followup_question_from_rules(matched_rule)
            reply = f"Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. {question}"
    else:
        logger.info("Herhangi bir rule eşleşmedi - OpenAI fallback deneniyor.")
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
    logger.info("Gönderilen cevap (sender=%s, len=%d): %s", sender, len(reply), reply[:300])
    return str(resp)

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp Dijital Asistan webhooku çalışıyor."

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
