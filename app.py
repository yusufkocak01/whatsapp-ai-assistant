#!/usr/bin/env python3
# app.py
"""
WhatsApp dijital asistan webhooku (Twilio uyumlu).
- prompt.csv (keyword,rules) okur
- keyword: virgül veya | ile ayrılmış alternatifler
- rules: virgül veya | ile ayrılmış örnek cevaplar
- matched rule -> önce rules içinden rastgele bir örnek alınır; eğer OPENAI varsa bu örnekler referans verilerek
  OpenAI'den daha doğal bir cevap üretilir (ör: "İyiyim, teşekkürler — ya sen?").
- unmatched -> OpenAI varsa ChatGPT tarzı cevap üretir; yoksa fallback.
- BOT ON / BOT OFF (admin numara) handoff desteği
"""
import os
import re
import time
import logging
import random
import difflib
from typing import Dict, List, Optional

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
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # optional, required for ChatGPT-like replies
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "300"))
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.45"))
ECHO_SIMILARITY_THRESHOLD = float(os.environ.get("ECHO_SIMILARITY_THRESHOLD", "0.45"))

# ADMIN_NUMBERS default as requested.
_default_admins = "whatsapp:+905322034617"
ADMIN_NUMBERS = set(
    n.strip() for n in os.environ.get("ADMIN_NUMBERS", _default_admins).split(",") if n.strip()
)

HANDOFF_TTL = int(os.environ.get("HANDOFF_TTL_SECONDS", str(60 * 60)))  # default 1 hour

HANDOFF_STATE: Dict[str, dict] = {}

app = Flask(__name__)

# ---------- Helper functions ----------

def load_prompts(csv_path: str):
    if not os.path.exists(csv_path):
        logger.warning("prompt.csv bulunamadı: %s", csv_path)
        return pd.DataFrame(columns=["keyword", "rules"])
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    if "keyword" not in df.columns or "rules" not in df.columns:
        raise ValueError("prompt.csv içinde 'keyword' ve 'rules' sütunları olmalı.")
    return df[["keyword", "rules"]]

def split_alternatives(s: str) -> List[str]:
    """Split by ',' or '|' and strip; ignore empty entries"""
    if not s:
        return []
    parts = re.split(r"\s*[|,]\s*", s)
    return [p.strip() for p in parts if p and p.strip()]

def find_rule_for_text(text: str, df: pd.DataFrame) -> Optional[str]:
    text_lower = (text or "").lower()
    for _, row in df.iterrows():
        raw_keys = row.get("keyword", "") or ""
        keys = split_alternatives(raw_keys)
        for k in keys:
            if not k:
                continue
            # whole-word match; note: \b works for many cases
            pattern = r"\b" + re.escape(k.lower()) + r"\b"
            if re.search(pattern, text_lower, flags=re.UNICODE):
                return row.get("rules", "")
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

# ---------- OpenAI helpers ----------

def generate_from_openai_with_examples(example_responses: List[str], user_message: str) -> Optional[str]:
    """
    Provide example responses and ask OpenAI to produce a short, conversational Turkish reply
    that is consistent with those examples. Returns None if OpenAI not configured or echo detected.
    """
    if not OPENAI_API_KEY or openai is None:
        logger.debug("OpenAI yok veya paket yüklü değil.")
        return None

    try:
        openai.api_key = OPENAI_API_KEY

        # Build an instruction that gives examples and asks for a natural reply
        examples_text = "Örnek cevaplar: " + "; ".join(example_responses) if example_responses else ""
        system_content = (
            "You are a Turkish conversational assistant. Produce a short, natural reply in Turkish. "
            "Do NOT output the instruction text or the example list verbatim. Use the examples as guidance for tone and possible phrasing.\n\n"
            f"{examples_text}\n\n"
            "Important: do not repeat the example list exactly; instead generate a natural reply similar in style."
        )
        user_content = (
            f"Kullanıcının mesajı: \"{user_message.strip()}\"\n\n"
            "Görev: Bu kullanıcıya kısa, nazik ve konuşma başlatıcı bir cevap üret. "
            "Cevapında kendini tek cümlede 'Yusuf Koçak'ın dijital asistanı' olarak tanıt ve sonuna konuşmayı sürdürecek bir soru ekle. "
            "Eğer örnek cevaplar verilmişse onlardan esinlen, fakat aynısını yazma."
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

        # Echo detection: if content is too similar to any example, treat as echo
        for ex in example_responses:
            sim = similarity(content, ex)
            logger.info("Similarity between generated content and example '%s' => %.3f", ex[:30], sim)
            if sim >= ECHO_SIMILARITY_THRESHOLD:
                logger.info("Detected likely echo to example; rejecting.")
                return None

        # also ensure it doesn't contain instruction strings
        lower = content.lower()
        if "örnek cevap" in lower or "talimat" in lower or "sen de aynı türden" in lower:
            logger.info("Detected forbidden phrase in response; treating as echo.")
            return None

        return content

    except Exception as e:
        logger.exception("OpenAI çağrısı sırasında hata: %s", e)
        return None

def generate_freeform_from_openai(user_message: str) -> Optional[str]:
    """
    If there is no matched rule, ask OpenAI to chat like ChatGPT in Turkish.
    """
    if not OPENAI_API_KEY or openai is None:
        return None
    try:
        openai.api_key = OPENAI_API_KEY
        system_content = (
            "You are a helpful Turkish conversational assistant (ChatGPT-like). "
            "Answer the user's message in Turkish in a friendly and concise way. "
            "Introduce yourself briefly as 'Yusuf Koçak'ın dijital asistanı' if appropriate."
        )
        user_content = f"Kullanıcının mesajı: \"{user_message.strip()}\"\n\nKısa ve doğal bir Türkçe cevap ver."

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
            return None
        choice0 = resp.choices[0]
        content = None
        if getattr(choice0, "message", None):
            content = choice0.message.get("content")
        elif getattr(choice0, "text", None):
            content = choice0.text
        if content:
            return content.strip()
        return None
    except Exception as e:
        logger.exception("OpenAI freeform hata: %s", e)
        return None

# ---------- Handoff helpers ----------
def normalize_sender(s: str) -> str:
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
        HANDOFF_STATE.pop(sender, None)
        return False
    return True

# ---------- Routes ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming = (request.values.get("Body") or "").strip()
    sender_raw = (request.values.get("From") or request.values.get("from") or "").strip()
    sender = normalize_sender(sender_raw)

    if not incoming:
        return ("", 204)

    logger.info("Gelen mesaj (sender=%s): %s", sender, incoming[:500])

    # load prompts
    try:
        df = load_prompts(CSV_PATH)
    except Exception as e:
        logger.exception("prompt.csv yüklenirken hata")
        resp = MessagingResponse()
        resp.message("Sunucuda prompt verisi yüklenemedi. Lütfen admin ile iletişime geçin.")
        return str(resp)

    # admin commands
    cmd = incoming.strip().lower()
    if is_admin(sender):
        if cmd in ("bot off", "stop bot", "bot kapat", "bot:off"):
            set_handoff(sender, by="admin")
            resp = MessagingResponse()
            resp.message("Bot devre dışı bırakıldı. Artık gelen mesajlara otomatik cevap gönderilmeyecek.")
            logger.info("Admin %s BOT OFF for %s", sender, sender)
            return str(resp)
        if cmd in ("bot on", "start bot", "bot aç", "bot:on"):
            clear_handoff(sender)
            resp = MessagingResponse()
            resp.message("Bot tekrar aktif edildi.")
            logger.info("Admin %s BOT ON for %s", sender, sender)
            return str(resp)

    # if handoff active -> do not reply (operator will handle)
    if check_handoff_active(sender):
        logger.info("Handoff aktif, bot cevap üretmiyor for %s", sender)
        return ("", 204)

    # normal processing
    matched_rules_text = find_rule_for_text(incoming, df)
    reply = None

    if matched_rules_text:
        # Split the rules into candidate example replies
        candidates = split_alternatives(matched_rules_text)
        # Prefer OpenAI-generated natural reply using examples (if available)
        ai_reply = None
        if candidates and OPENAI_API_KEY and openai is not None:
            ai_reply = generate_from_openai_with_examples(candidates, incoming)
        if ai_reply:
            reply = ai_reply
        else:
            # If no OpenAI or OpenAI refused due to echo detection, pick a random candidate
            if candidates:
                chosen = random.choice(candidates)
                # Make reply slightly friendlier: add assistant intro and a follow-up question
                followup = pick_followup_question_from_rules(matched_rules_text) if 'pick_followup_question_from_rules' in globals() else ""
                # If chosen already is a short phrase like 'İyiyim', we can extend it naturally:
                if len(chosen) < 40:
                    reply = f"{chosen}. Ben Yusuf Koçak'ın dijital asistanıyım. {followup}"
                else:
                    reply = f"{chosen} Ben Yusuf Koçak'ın dijital asistanıyım. {followup}"
            else:
                # no candidates: fallback to a general question
                reply = "Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. Size nasıl yardımcı olabilirim?"
    else:
        # no rule matched -> freeform OpenAI chat if available
        ai_reply = generate_freeform_from_openai(incoming)
        if ai_reply:
            reply = ai_reply
        else:
            # fallback if OpenAI not available
            reply = (
                "Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. "
                "Mesajınızı tam anlayamadım. Kısaca ne yapmak istediğinizi yazabilir misiniz? "
                "Örneğin: 'randevu oluştur', 'fiyat bilgisi', 'iletişim' vb."
            )

    # send via Twilio TwiML
    resp = MessagingResponse()
    resp.message(reply)
    logger.info("Gönderilen cevap (sender=%s, len=%d): %s", sender, len(reply), reply[:300])
    return str(resp)

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp Dijital Asistan webhooku çalışıyor."

# ---------- small fallback for functions used above (to keep code self-contained) ----------
def pick_followup_question_from_rules(rules_text: str):
    rt = (rules_text or "").lower()
    if any(k in rt for k in ["randevu", "tarih", "saat"]):
        return "Hangi tarih ve saat için istersiniz?"
    if any(k in rt for k in ["fiyat", "ücret"]):
        return "Hangi hizmet için fiyat almak istiyorsunuz?"
    if any(k in rt for k in ["iletişim", "telefon", "mail", "e-posta"]):
        return "Telefon mu yoksa e-posta mı tercih edersiniz?"
    return "Size nasıl yardımcı olabilirim? Hangi konuda yardım istersiniz?"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
