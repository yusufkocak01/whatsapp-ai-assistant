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
    # Unicode combining karakterleri temizle
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    # Küçük harfe çevir ve fazla boşlukları temizle
    return re.sub(r'\s+', ' ', text.strip().lower())

def normalize_city(text):
    """Şehir/ilçe isimlerini standartlaştır (Türkçe karakter dönüştürme yok, sadece küçük harf + temizleme)"""
    text = normalize_text(text)
    # Türkçe karakterleri Latin karşılığına çevir (opsiyonel, isterseniz açabilirsiniz)
    # turkish_map = str.maketrans("çğıöşü", "cgiosu")
    # text = text.translate(turkish_map)
    return text

def extract_location(text):
    """
    Basit konum çıkarma: ilk 1-2 kelimeyi il/ilçe olarak kabul eder.
    İleride NLP ile geliştirilebilir.
    """
    words = normalize_city(text).split()
    if len(words) >= 2:
        return words[0], words[1]  # il, ilçe
    elif len(words) == 1:
        return words[0], words[0]  # ilçe = il (örn: "Maraş" → il=ilçe="maraş")
    return None, None

def format_link(link):
    if not link or link.lower() in ["", "none", "null"]:
        return ""
    link = link.strip()
    if not link.startswith(("http://", "https://")):
        link = "https://" + link
    return link

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").strip()
    resp = MessagingResponse()
    msg = resp.message()

    if not incoming_msg:
        return str(resp)

    # Oturum varsa, konum bilgisi bekleniyor
    if from_number in user_sessions:
        session = user_sessions[from_number]
        if session["state"] == "waiting_for_location":
            il, ilce = extract_location(incoming_msg)
            if il and ilce:
                packages = load_packages()
                if not packages:
                    msg.body("Paket bilgileri yüklenemiyor. Lütfen daha sonra tekrar deneyin.")
                    return str(resp)

                # Kategoriye göre filtrele (örn: "palyaço")
                target_category = session["intent"]
                matches = []
                for p in packages:
                    if (
                        normalize_city(p["il"]) == normalize_city(il) and
                        normalize_city(p["ilce"]) == normalize_city(ilce) and
                        normalize_city(p["kategori"]) == normalize_city(target_category)
                    ):
                        matches.append(p["url"])

                if matches:
                    response_text = f"✅ {il.title()} / {ilce.title()} için uygun {target_category} paketleri:\n\n"
                    for url in matches[:5]:  # En fazla 5 paket göster
                        response_text += f"👉 {url}\n"
                    msg.body(response_text)
                else:
                    msg.body(f"Üzgünüz, {il.title()} / {ilce.title()} bölgesinde şu anda uygun {target_category} paketi bulunmuyor.")
            else:
                msg.body("Lütfen il ve ilçe bilgisini yazın (örneğin: Adana Kozan).")

            # Oturumu temizle
            user_sessions.pop(from_number, None)
            return str(resp)

    # Oturum yoksa — genel kuralları kontrol et
    rules_list = load_rules()
    if rules_list is None:
        return str(resp)

    normalized_input = normalize_text(incoming_msg)
    matched_responses = []
    used_keywords = set()

    # TAM EŞLEŞME
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

    # İÇERME EŞLEŞMESİ
    for rule in rules_list:
        kw = normalize_text(rule["keyword"])
        if not kw or kw in used_keywords:
            continue
        if kw in normalized_input:
            if kw in used_keywords:
                continue
            used_keywords.add(kw)
            response_text = rule["rules"]
            link = format_link(rule["link"])
            if link:
                response_text += "\n\n" + link
            matched_responses.append(response_text)

    # Özel niyetler: palyaço, mehter, dini düğün, vs.
    intents = ["palyaço", "mehter", "dini düğün", "bando", "karagöz"]
    detected_intent = None
    for intent in intents:
        if normalize_city(intent) in normalized_input:
            detected_intent = intent
            break

    if detected_intent:
        user_sessions[from_number] = {
            "state": "waiting_for_location",
            "intent": detected_intent
        }
        msg.body(f"📍 {detected_intent} hizmeti için lütfen il ve ilçe yazınız (örneğin: Adana Kozan).")
        return str(resp)

    # Normal cevaplar
    if matched_responses:
        full_message = "\n\n".join(matched_responses)
        msg.body(full_message)

    return str(resp)

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Dinamik WhatsApp Asistan çalışıyor: prompt + packages + multi-keyword + stateful flow"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
