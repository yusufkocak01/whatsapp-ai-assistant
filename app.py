# app.py
import os
import csv
import io
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import re

app = Flask(__name__)

# 🔁 GitHub raw linkini DÜZELTTİM: sondaki boşluk KALDIRILDI!
GITHUB_CSV_URL = "https://raw.githubusercontent.com/yusufkocak01/whatsapp-ai-assistant/main/prompt.csv"

def load_rules():
    try:
        response = requests.get(GITHUB_CSV_URL, timeout=10)
        response.raise_for_status()
        content = response.content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        rules = []
        for row in reader:
            if row.get("keyword") and row.get("rules") is not None:
                rules.append({
                    "keyword": row["keyword"].strip(),
                    "rules": row["rules"].strip(),
                    "link": row.get("link", "").strip()
                })
        return rules
    except Exception as e:
        print("❗ CSV yüklenemedi:", e)
        return None

def normalize_text(text):
    return re.sub(r'\s+', ' ', text.strip().lower())

def format_link(link):
    """Link'i güvenli şekilde formatlar."""
    if not link or link.lower() in ["", "none", "null"]:
        return ""
    link = link.strip()
    if not link.startswith(("http://", "https://")):
        link = "https://" + link
    return link

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    if not incoming_msg:
        return str(resp)

    rules_list = load_rules()
    if rules_list is None:
        return str(resp)

    normalized_input = normalize_text(incoming_msg)
    matched_responses = []
    used_keywords = set()  # Tekrarı önlemek için

    # 🔍 1. TAM EŞLEŞME kontrolü
    for rule in rules_list:
        kw = normalize_text(rule["keyword"])
        if kw == normalized_input:
            if kw in used_keywords:
                continue
            used_keywords.add(kw)
            response_text = rule["rules"]
            link = format_link(rule["link"])
            if link:
                response_text += "\n\n" + link
            matched_responses.append(response_text)

    # 🔍 2. İÇERME EŞLEŞMESİ (ama tam eşleşenler hariç)
    for rule in rules_list:
        kw = normalize_text(rule["keyword"])
        if not kw:
            continue
        if kw in used_keywords:
            continue  # Zaten tam eşleşmeyle gönderildi
        if kw in normalized_input:
            if kw in used_keywords:
                continue
            used_keywords.add(kw)
            response_text = rule["rules"]
            link = format_link(rule["link"])
            if link:
                response_text += "\n\n" + link
            matched_responses.append(response_text)

    # ✉️ Eşleşen cevaplar varsa, hepsini birleştirip gönder
    if matched_responses:
        full_message = "\n\n".join(matched_responses)
        msg.body(full_message)

    # ❌ Eşleşme yoksa: sessiz kal (isteğe bağlı uyarı eklenebilir)

    return str(resp)

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Çoklu keyword destekli WhatsApp Asistan çalışıyor!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
