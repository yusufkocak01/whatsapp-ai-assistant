#!/usr/bin/env python3

# app.py

"""
WhatsApp dijital asistan webhooku (Twilio uyumlu).

* prompt.csv (keyword,rules) okur
* keyword: virgül veya | ile ayrılmış alternatifler
* rules: virgül veya | ile ayrılmış örnek cevaplar
* matched rule -> önce rules içinden rastgele bir örnek alınır; OpenAI varsa doğal cevap üretir
* unmatched -> OpenAI varsa ChatGPT tarzı cevap üretir; yoksa fallback
* BOT ON / BOT OFF (admin numara) handoff desteği
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
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # optional
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "300"))
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.45"))
ECHO_SIMILARITY_THRESHOLD = float(os.environ.get("ECHO_SIMILARITY_THRESHOLD", "0.45"))

# ADMIN_NUMBERS default

_default_admins = "whatsapp:+905322034617"
ADMIN_NUMBERS = set(
n.strip() for n in os.environ.get("ADMIN_NUMBERS", _default_admins).split(",") if n.strip()
)

HANDOFF_TTL = int(os.environ.get("HANDOFF_TTL_SECONDS", str(60 * 60)))  # default 1 hour
HANDOFF_STATE: Dict[str, dict] = {}

app = Flask(**name**)

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
if not s:
return []
parts = re.split(r"\s*[|,]\s*", s)
return [p.strip() for p in parts if p.strip()]

def normalize_text(text: str) -> str:
text_lower = (text or "").lower()
return re.sub(r"[^\w\s]", "", text_lower)  # noktalama kaldır

def find_rule_for_text(text: str, df: pd.DataFrame) -> Optional[str]:
text_norm = normalize_text(text)
for _, row in df.iterrows():
keys = split_alternatives(row.get("keyword", ""))
for k in keys:
k_norm = normalize_text(k)
if k_norm in text_norm:
return row.get("rules", "")
return None

def similarity(a: str, b: str) -> float:
if not a or not b:
return 0.0
return difflib.SequenceMatcher(None, a, b).ratio()

# ---------- OpenAI helpers ----------

def generate_from_openai_with_examples(example_responses: List[str], user_message: str) -> Optional[str]:
if not OPENAI_API_KEY or openai is None:
return None
try:
openai.api_key = OPENAI_API_KEY
examples_text = "Örnek cevaplar: " + "; ".join(example_responses) if example_responses else ""
system_content = (
"You are a Turkish conversational assistant. Produce a short, natural reply in Turkish. "
f"{examples_text}"
)
user_content = (
f"Kullanıcının mesajı: "{user_message.strip()}"\n"
"Kısa, nazik, doğal bir cevap üretin. "
"Kendinizi tek cümlede 'Yusuf Koçak'ın dijital asistanı' olarak tanıtın ve konuşmayı sürdürecek bir soru ekleyin."
)
resp = openai.ChatCompletion.create(
model=OPENAI_MODEL,
messages=[{"role": "system", "content": system_content}, {"role": "user", "content": user_content}],
max_tokens=MAX_TOKENS,
temperature=TEMPERATURE,
)
content = resp.choices[0].message.get("content", "").strip() if resp.choices else None
for ex in example_responses:
if similarity(content, ex) >= ECHO_SIMILARITY_THRESHOLD:
return None
return content
except Exception as e:
logger.exception("OpenAI örnek cevap hatası: %s", e)
return None

def generate_freeform_from_openai(user_message: str) -> Optional[str]:
if not OPENAI_API_KEY or openai is None:
return None
try:
openai.api_key = OPENAI_API_KEY
system_content = (
"You are a helpful Turkish conversational assistant (ChatGPT-like). "
"Answer the user's message in Turkish in a friendly and concise way. "
"Introduce yourself briefly as 'Yusuf Koçak'ın dijital asistanı' if appropriate."
)
user_content = f"Kullanıcının mesajı: "{user_message.strip()}"\nKısa ve doğal bir cevap ver."
resp = openai.ChatCompletion.create(
model=OPENAI_MODEL,
messages=[{"role": "system", "content": system_content}, {"role": "user", "content": user_content}],
max_tokens=MAX_TOKENS,
temperature=TEMPERATURE,
)
content = resp.choices[0].message.get("content", "").strip() if resp.choices else None
return content
except Exception as e:
logger.exception("OpenAI freeform hatası: %s", e)
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

```
if not incoming:
    return ("", 204)

logger.info("Gelen mesaj (sender=%s): %s", sender, incoming[:500])

try:
    df = load_prompts(CSV_PATH)
except Exception:
    resp = MessagingResponse()
    resp.message("Sunucuda prompt verisi yüklenemedi. Lütfen admin ile iletişime geçin.")
    return str(resp)

# admin commands
cmd = incoming.lower()
if is_admin(sender):
    if cmd in ("bot off", "stop bot", "bot kapat", "bot:off"):
        set_handoff(sender, by="admin")
        resp = MessagingResponse()
        resp.message("Bot devre dışı bırakıldı.")
        return str(resp)
    if cmd in ("bot on", "start bot", "bot aç", "bot:on"):
        clear_handoff(sender)
        resp = MessagingResponse()
        resp.message("Bot tekrar aktif edildi.")
        return str(resp)

if check_handoff_active(sender):
    return ("", 204)

# normal processing
matched_rules_text = find_rule_for_text(incoming, df)
reply = None

if matched_rules_text:
    candidates = split_alternatives(matched_rules_text)
    ai_reply = generate_from_openai_with_examples(candidates, incoming)
    if ai_reply:
        reply = ai_reply
    else:
        chosen = random.choice(candidates) if candidates else "Merhaba"
        reply = f"{chosen}. Ben Yusuf Koçak'ın dijital asistanıyım. {pick_followup_question_from_rules(matched_rules_text)}"
else:
    ai_reply = generate_freeform_from_openai(incoming)
    if ai_reply:
        reply = ai_reply
    else:
        reply = (
            "Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. "
            "Mesajınızı tam anlayamadım. Kısaca ne yapmak istediğinizi yazabilir misiniz?"
        )

resp = MessagingResponse()
resp.message(reply)
logger.info("Cevap gönderildi (len=%d): %s", len(reply), reply[:300])
return str(resp)
```

@app.route("/", methods=["GET"])
def index():
return "WhatsApp Dijital Asistan webhooku çalışıyor."

# ---------- Followup helper ----------

def pick_followup_question_from_rules(rules_text: str):
rt = (rules_text or "").lower()
if any(k in rt for k in ["randevu", "tarih", "saat"]):
return "Hangi tarih ve saat için istersiniz?"
if any(k in rt for k in ["fiyat", "ücret"]):
return "Hangi hizmet için fiyat almak istiyorsunuz?"
if any(k in rt for k in ["iletişim", "telefon", "mail", "e-posta"]):
return "Telefon mu yoksa e-posta mı tercih edersiniz?"
return "Size nasıl yardımcı olabilirim? Hangi konuda yardım istersiniz?"

if **name** == "**main**":
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
