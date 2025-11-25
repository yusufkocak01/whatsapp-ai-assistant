#!/usr/bin/env python3

# app.py

"""
WhatsApp dijital asistan webhooku (Twilio uyumlu).

* prompt.csv sadece 'rules' sütunu içerir
* Her 'rules' satırı, botun mesajlara nasıl cevap vereceğini belirten bir prompt/metindir
* Gelen mesaj, satırların tümü ile test edilip OpenAI’ye gönderilir
* BOT ON / BOT OFF (admin numara) handoff desteği
  """
  import os
  import time
  import logging
  import csv
  from typing import Dict, List

from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import openai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp-assistant")

CSV_PATH = os.environ.get("PROMPT_CSV", "prompt.csv")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "300"))
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.45"))

_default_admins = "whatsapp:+905322034617"
ADMIN_NUMBERS = set(
n.strip() for n in os.environ.get("ADMIN_NUMBERS", _default_admins).split(",") if n.strip()
)

HANDOFF_TTL = int(os.environ.get("HANDOFF_TTL_SECONDS", str(60 * 60)))
HANDOFF_STATE: Dict[str, dict] = {}

app = Flask(**name**)

# ---------- Helper ----------

def load_rules(csv_path: str) -> List[str]:
"""prompt.csv dosyasını 'rules' sütunundan okur."""
try:
with open(csv_path, "r", encoding="utf-8") as f:
reader = csv.DictReader(f)
if "rules" not in reader.fieldnames:
raise ValueError("CSV dosyasında 'rules' sütunu bulunmalı.")
return [row["rules"].strip() for row in reader if row.get("rules", "").strip()]
except FileNotFoundError:
logger.warning("prompt.csv bulunamadı: %s", csv_path)
return []
except Exception as e:
logger.error("CSV okuma hatası: %s", e)
return []

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

# ---------- OpenAI ----------

openai.api_key = OPENAI_API_KEY

def generate_reply(rules_list: List[str], user_message: str) -> str:
if not OPENAI_API_KEY:
return "Mesajınızı aldım, ancak bot AI desteği şu anda yok."

```
combined_rules = "\n".join(rules_list)

prompt = (
    f"Rules metni:\n{combined_rules}\n\n"
    f"Kullanıcının mesajı: {user_message}\n\n"
    "Kuralları uygulayarak, kısa, samimi ve anlaşılır bir Türkçe cevap verin. "
    "Kendinizi 'Yusuf Koçak'ın dijital asistanı' olarak tanıtın ve cevabı bir soru ile bitirerek konuşmayı devam ettirin."
)

try:
    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    content = resp.choices[0].message.get("content", "").strip() if resp.choices else None
    return content or "Mesajınızı aldım, ancak cevap üretilemedi."
except Exception as e:
    logger.exception("OpenAI cevap üretme hatası: %s", e)
    return "Mesajınızı aldım ama şu anda bir sorun oluştu."
```

# ---------- Routes ----------

@app.route("/webhook", methods=["POST"])
def webhook():
incoming = (request.values.get("Body") or "").strip()
sender = (request.values.get("From") or "").strip()

```
if not incoming or not sender:
    return ("", 204)

logger.info("Gelen mesaj (sender=%s): %s", sender, incoming[:500])

rules_list = load_rules(CSV_PATH)
if not rules_list:
    resp = MessagingResponse()
    resp.message("Sunucuda prompt verisi yüklenemedi. Lütfen admin ile iletişime geçin.")
    return str(resp)

cmd = incoming.lower()
if is_admin(sender):
    resp = MessagingResponse()
    if cmd in ("bot off", "stop bot", "bot kapat", "bot:off"):
        set_handoff(sender)
        resp.message("Bot devre dışı bırakıldı.")
        return str(resp)
    if cmd in ("bot on", "start bot", "bot aç", "bot:on"):
        clear_handoff(sender)
        resp.message("Bot tekrar aktif edildi.")
        return str(resp)

if check_handoff_active(sender):
    return ("", 204)

reply = generate_reply(rules_list, incoming)
resp = MessagingResponse()
resp.message(reply)
return str(resp)
```

@app.route("/", methods=["GET"])
def index():
return "WhatsApp Dijital Asistan webhooku çalışıyor."

if **name** == "**main**":
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
