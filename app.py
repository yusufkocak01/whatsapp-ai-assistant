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

# GitHub CSV URL'leri
GITHUB_PROMPT_CSV_URL = "https://raw.githubusercontent.com/yusufkocak01/whatsapp-ai-assistant/main/prompt.csv"
GITHUB_PACKAGES_CSV_URL = "https://raw.githubusercontent.com/yusufkocak01/whatsapp-ai-assistant/main/packages.csv"

# Oturum takibi (production'da Redis önerilir)
user_sessions = {}

# --- YARDIMCI FONKSİYONLAR ---
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
            if row.get("url") and row.get("il") and row.get("ilce") and row.get("kategori"):
                packages.append({
                    "url": row["url"].strip(),
                    "il": row["il"].strip(),
                    "ilce": row["ilce"].strip(),
                    "kategori": row["kategori"].strip()
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

# --- WHATSAPP WEBHOOK ---
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    if not incoming_msg:
        return str(resp)

    normalized_input = normalize_text(incoming_msg)

    # --- Oturum varsa, konum bilgisi bekleniyor ---
    if from_number in user_sessions:
        session = user_sessions[from_number]
        if session["state"] == "waiting_for_location":
            il, ilce = extract_location(incoming_msg)
            packages = load_packages()
            if not packages:
                msg.body("Paket bilgileri yüklenemiyor. Lütfen daha sonra tekrar deneyin.")
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
                response_text = f"✅ {target_category.title()} için şu linklere bakabilirsiniz. Bu paketlerde fiyat bilgisi de mevcut:\n\n"
                for p in matches[:5]:
                    response_text += f"👉 {p['url']}\n"
                msg.body(response_text)
            else:
                msg.body(f"Üzgünüz, {il.title()} / {ilce.title() if ilce else 'merkez'} bölgesinde şu anda uygun {target_category} paketi bulunmuyor.")

            # Oturumu temizle
            user_sessions.pop(from_number, None)
            return str(resp)

    # --- Oturum yoksa: önce Giriş sekmesinden cevap ver ---
    rules_list = load_rules()
    if rules_list is None:
        return str(resp)

    matched_responses = []
    used_keywords = set()

    for rule in rules_list:
        kw = normalize_text(rule["keyword"])
        if kw in used_keywords or not kw:
            continue
        if kw == normalized_input or kw in normalized_input:
            used_keywords.add(kw)
            response_text = rule["rules"]
            link = format_link(rule.get("link", ""))
            if link:
                response_text += "\n\n" + link
            matched_responses.append(response_text)

    if matched_responses:
        msg.body("\n\n".join(matched_responses))
        return str(resp)

    # --- Özel niyetler ---
    intents_map = {
        "palyaço": "palyaço",
        "mehter": "mehter",
        "dini düğün": "ilahi grubu",
        "bando": "bando",
        "karagöz": "karagöz",
        "sünnet": "sünnet düğünü",
        "ilahi": "ilahi grubu"
    }

    detected_intent = None
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

    # --- Son çare: yönlendirme sorusu ---
    msg.body("Hangi hizmetle ilgileniyorsunuz? Palyaço, Sünnet düğünü, Mehter, Bando, Karagöz, İlahi Grubu gibi seçeneklerden birini yazabilirsiniz.")
    return str(resp)

# --- SAĞLIK KONTROL ---
@app.route("/", methods=["GET"])
def health_check():
    return "✅ Dinamik WhatsApp Asistan çalışıyor: prompt + packages + multi-keyword + stateful flow"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
