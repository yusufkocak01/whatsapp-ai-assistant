# app.py
import os
import csv
import io
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import re
import unicodedata

app = Flask(__name__)

GITHUB_PROMPT_CSV_URL = "https://raw.githubusercontent.com/yusufkocak01/whatsapp-ai-assistant/main/prompt.csv"
GITHUB_PACKAGES_CSV_URL = "https://raw.githubusercontent.com/yusufkocak01/whatsapp-ai-assistant/main/packages.csv"

user_sessions = {}

# --- Yardımcı Fonksiyonlar ---
def load_rules():
    try:
        response = requests.get(GITHUB_PROMPT_CSV_URL, timeout=10)
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
        print("❗ prompt.csv yüklenemedi:", e)
        return None

def load_packages():
    try:
        response = requests.get(GITHUB_PACKAGES_CSV_URL, timeout=10)
        response.raise_for_status()
        content = response.content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        packages = []
        for row in reader:
            if row.get("url") and row.get("il") and row.get("ilce") and row.get("kategori") and row.get("aciklama"):
                packages.append({
                    "url": row["url"].strip(),
                    "il": row["il"].strip(),
                    "ilce": row["ilce"].strip(),
                    "kategori": row["kategori"].strip(),
                    "aciklama": row["aciklama"].strip()
                })
        return packages
    except Exception as e:
        print("❗ packages.csv yüklenemedi:", e)
        return None

def normalize_text(text):
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text.strip().lower())

def normalize_city(text):
    return normalize_text(text)

def extract_location(text):
    words = normalize_city(text).split()
    if len(words) >= 2:
        return words[0], words[1]
    elif len(words) == 1:
        return words[0], None
    return None, None

def format_link(link):
    if not link or link.lower() in ["", "none", "null"]:
        return ""
    link = link.strip()
    if not link.startswith(("http://", "https://")):
        link = "https://" + link
    return link

# --- WhatsApp Webhook ---
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    if not incoming_msg:
        return str(resp)

    normalized_input = normalize_text(incoming_msg)

    # --- Oturum varsa ---
    if from_number in user_sessions:
        session = user_sessions[from_number]

        # Paket kategorisi seçildiyse, il/ilçe bekleniyor
        if session.get("state") == "waiting_for_location":
            il, ilce = extract_location(incoming_msg)
            packages = load_packages()
            if not packages:
                msg.body("Paket bilgileri yüklenemiyor, lütfen daha sonra tekrar deneyin.")
                return str(resp)

            target_category = session["intent"]
            matches = []

            if il and not ilce:
                for p in packages:
                    if normalize_city(p["il"]) == normalize_city(il) and "merkez" in normalize_city(p["ilce"]) and normalize_city(p["kategori"]) == normalize_city(target_category):
                        matches.append(p)
            elif il and ilce:
                for p in packages:
                    if normalize_city(p["il"]) == normalize_city(il) and normalize_city(p["ilce"]) == normalize_city(ilce) and normalize_city(p["kategori"]) == normalize_city(target_category):
                        matches.append(p)

            if matches:
                response_text = f"✅ {target_category.title()} için uygun paketler ve kısa açıklamaları:\n\n"
                for p in matches[:5]:
                    response_text += f"👉 {p['aciklama']}\n   {p['url']}\n"
                msg.body(response_text)
            else:
                msg.body(f"Üzgünüz, {il.title()} / {ilce.title() if ilce else 'merkez'} bölgesinde uygun {target_category} paketi bulunmuyor.")

            user_sessions.pop(from_number, None)
            return str(resp)

        # Oturumda “Neyle ilgili bilgi vereyim?” sorusu varsa
        elif session.get("state") == "waiting_for_category":
            detected_intent = None
            intents_map = {
                "palyaço": "palyaço",
                "mehter": "mehter",
                "dini düğün": "ilahi grubu",
                "bando": "bando",
                "karagöz": "karagöz",
                "sünnet": "sünnet düğünü",
                "ilahi": "ilahi grubu"
            }
            for keyword, intent in intents_map.items():
                if keyword in normalized_input:
                    detected_intent = intent
                    break

            if detected_intent:
                user_sessions[from_number] = {
                    "state": "waiting_for_location",
                    "intent": detected_intent
                }
                msg.body(f"📍 {detected_intent} hizmeti için il ve/veya ilçe yazınız (örn: Adana Kozan).")
                return str(resp)
            else:
                msg.body("Maalesef bu hizmeti tanımıyorum. Lütfen Palyaço, Mehter, Bando, Karagöz, Sünnet, İlahi Grubu gibi seçeneklerden birini yazınız.")
                return str(resp)

    # --- Önce Giriş sekmesine bak ---
    rules_list = load_rules()
    if rules_list:
        for rule in rules_list:
            kw = normalize_text(rule["keyword"])
            if kw and (kw == normalized_input or kw in normalized_input):
                response_text = rule["rules"]
                link = format_link(rule.get("link", ""))
                if link:
                    response_text += f"\n\n{link}"
                msg.body(response_text)
                return str(resp)

    # --- Giriş yoksa: paket seçimi ---
    user_sessions[from_number] = {"state": "waiting_for_category"}
    msg.body("Neyle ilgili bilgi vereyim? (örn: Palyaço, Sünnet düğünü, Mehter, Bando, Karagöz, İlahi Grubu)")
    return str(resp)

# --- Sağlık kontrol ---
@app.route("/", methods=["GET"])
def health_check():
    return "✅ Dinamik WhatsApp Asistan çalışıyor: prompt + packages + multi-keyword + stateful flow"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
