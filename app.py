#!/usr/bin/env python3

# app.py

"""
WhatsApp dijital asistan webhooku (Twilio uyumlu) - BOT ON/OFF özelliği ile
"""
import os
import re
import time
import logging
from typing import Dict

from flask import Flask, request
import pandas as pd

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
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "300"))
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.45"))

# Admin numaraları

_default_admins = "whatsapp:+905322034617"
ADMIN_NUMBERS = set(
n.strip() for n in os.environ.get("ADMIN_NUMBERS", _default_admins).split(",") if n.strip()
)

# BOT handoff state

HANDOFF_STATE: Dict[str, dict] = {}
HANDOFF_TTL = int(os.environ.get("HANDOFF_TTL_SECONDS", str(60*60)))  # 1 saat default

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

def normalize_text(text: str) -> str:
return re.sub(r"[^\w\s]", "", (text or "").lower())

def find_rule_for_text(text: str, df):
text_norm = normalize_text(text)
for _, row in df.iterrows():
k = normalize_text(row.get("keyword", ""))
if k and k in text_norm:
return row.get("rules", "")
return None

# ---------- OpenAI helper ----------

def generate_reply_from_prompt(rule_prompt: str, user_message: str) -> str:
if OPENAI_API_KEY and openai:
try:
openai.api_key = OPENAI_API_KEY
system_content = (
"You are a Turkish assistant. Produce a natural, friendly, concise reply based on the given prompt."
)
user_content = (
f"Rules prompt: "{rule_prompt.strip()}"\n"
f"Kullanıcı mesajı: "{user_message.strip()}"\n"
"Cevabı kısa, anlaşılır ve samimi şekilde yazın. "
"Kendinizi 'Yusuf Koçak'ın dijital asistanı' olarak tanıtın ve kullanıcıya sorusunu sorun."
)
resp = openai.ChatCompletion.create(
model=OPENAI_MODEL,
messages=[{"role": "system", "content": system_content},
{"role": "user", "content": user_content}],
max_tokens=MAX_TOKENS,
temperature=TEMPERATURE,
)
content = resp.choices[0].message.get("content", "").strip() if resp.choices else None
if content:
return content
except Exception as e:
logger.exception("OpenAI cevap üretme hatası: %s", e)
return f"{rule_prompt.strip()} Size nasıl yardımcı olabilirim?"

# ---------- Handoff helpers ----------

def normalize_sender(s: str) -> str:
return (s or "").strip()

def is_admin(sender: str) -> bool:
return sender in ADMIN_NUMBERS

def set_handoff(sender: str):
HANDOFF_STATE[sender] = {"handed_off": True, "since": time.time()}

def clear_handoff(sender: str):
HANDOFF_STATE.pop(sender, None)

def check_handoff_active(sender: str) -> bool:
state = HANDOFF_STATE.get(sender)
if not state:
return False
if time.time() - state.get("since", 0) > HANDOFF_TTL:
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

cmd = incoming.lower()
if is_admin(sender):
    if cmd in ("bot off", "stop bot", "bot kapat", "bot:off"):
        set_handoff(sender)
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

rule_prompt = find_rule_for_text(incoming, df)
if rule_prompt:
    reply = generate_reply_from_prompt(rule_prompt, incoming)
else:
    reply = f"Merhaba — ben Yusuf Koçak'ın dijital asistanıyım. Mesajınızı tam anlayamadım. Kısaca ne yapmak istediğinizi yazabilir misiniz?"

resp = MessagingResponse()
resp.message(reply)
logger.info("Cevap gönderildi (len=%d): %s", len(reply), reply[:300])
return str(resp)
```

@app.route("/", methods=["GET"])
def index():
return "WhatsApp Dijital Asistan webhooku çalışıyor."

if **name** == "**main**":
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
