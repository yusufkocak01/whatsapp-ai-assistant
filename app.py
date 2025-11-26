# app.py
from flask import Flask, request
import os
import requests
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# Gemini API URL ve Key
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta2/models/text-bison-001:generateMessage"
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Tüm linkler
with open("links.txt", "r", encoding="utf-8") as f:
    ALL_URLS = [line.strip() for line in f if line.strip()]

# Desteklenen şehirler
CITIES = ["Adana", "Niğde", "Mersin", "Kahramanmaraş", "Hatay",
          "Gaziantep", "Osmaniye", "Kilis", "Aksaray"]

# Hafızada session
sessions = {}

def generate_gemini_reply(messages):
    prompt = "\n".join([m['content'] for m in messages])
    headers = {
        "Authorization": f"Bearer {GEMINI_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "prompt": prompt,
        "temperature": 0.6,
        "candidate_count": 1
    }
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        return result.get("candidates", [{}])[0].get("content", "")
    except Exception as e:
        return f"Hata Gemini API: {str(e)}"

def find_matches(filters):
    matches = []
    city = filters.get("city", "").lower() if filters.get("city") else ""
    district = filters.get("district", "").lower() if filters.get("district") else ""
    service = filters.get("service_type")
    detail = filters.get("detail")

    for url in ALL_URLS:
        u = url.lower()
        if city and not u.startswith(f"https://israorganizasyon.com/{city.lower()}"):
            continue
        if district:
            parts = url.replace("https://israorganizasyon.com/", "").split("-")
            if len(parts) < 2:
                continue
            if district not in parts[1].lower():
                continue
        if service == "mehter" and "mehter" not in u:
            continue
        if service == "palyaco" and "palyaco" not in u:
            continue
        if service in ["sunnet_dugunu", "dini_dugun"] and not ("sunnet" in u or "dugunu" in u):
            continue
        if service == "bando" and "bando" not in u:
            continue
        if service == "karagoz" and ("karagoz" not in u and "golge" not in u):
            continue
        if service == "mehter" and detail:
            if f"-{detail}." not in u:
                continue
        if service == "palyaco":
            if detail == "2-saat" and "2-saat" not in u:
                continue
            if detail == "tum-gun" and "tum-gun" not in u:
                continue
        matches.append(url)
    return matches[:3]

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    from_number = request.values.get("From")
    body = request.values.get("Body", "").strip()
    response = MessagingResponse()

    if not from_number or not body:
        return str(response)

    if from_number not in sessions:
        sessions[from_number] = {
            "messages": [
                {"role": "system",
                 "content": ("Sen, İsra Organizasyon’un samimi WhatsApp asistanısın. "
                             "Müşteriden doğal sorularla şunları öğren: il, ilçe, hizmet türü (mehter, palyaço, dini düğün/sunnet, bando, karagöz), "
                             "ve gerekirse detay (mehter kişi sayısı, palyaço süre). "
                             "Yanıtlar kısa, samimi ve Türkçe olmalı. Sadece tam bilgi olduğunda uygun link öner. "
                             "Tahminle asla link önerme.")}
            ],
            "filters": {}
        }

    session = sessions[from_number]
    session["messages"].append({"role": "user", "content": body})
    text = body.lower()
    filters = session["filters"]

    # Şehir tespiti
    for city in CITIES:
        if city.lower() in text:
            filters["city"] = city

    # İlçe tespiti
    known_districts = {url.split("/")[3].split("-")[1] for url in ALL_URLS if len(url.split("/")) > 3}
    for d in known_districts:
        if d.lower() in text:
            filters["district"] = d

    # Hizmet türü
    if "mehter" in text:
        filters["service_type"] = "mehter"
    elif "palyaço" in text or "palyaco" in text:
        filters["service_type"] = "palyaco"
    elif "dini düğün" in text or "nikah" in text or "sunnet" in text or "düğün" in text:
        filters["service_type"] = "sunnet_dugunu"
    elif "bando" in text:
        filters["service_type"] = "bando"
    elif "karagöz" in text or "gölge" in text or "hacivat" in text:
        filters["service_type"] = "karagoz"

    # Detaylar
    if filters.get("service_type") == "mehter":
        for size in ["8", "12", "18", "24", "30", "32"]:
            if size in text:
                filters["detail"] = size
                break
    if filters.get("service_type") == "palyaco":
        if "2 saat" in text or "2-saat" in text:
            filters["detail"] = "2-saat"
        elif "tüm gün" in text or "tum gun" in text:
            filters["detail"] = "tum-gun"

    # Gemini cevabı
    ai_reply = generate_gemini_reply(session["messages"])
    session["messages"].append({"role": "assistant", "content": ai_reply})

    # Eğer tüm filtreler tamam ise link öner
    if (filters.get("city") and filters.get("district") and filters.get("service_type") and
        (filters["service_type"] not in ["mehter", "palyaco"] or filters.get("detail"))):
        matches = find_matches(filters)
        if matches and "http" not in ai_reply:
            ai_reply += "\n\nİşte size uygun paketler:\n" + "\n".join(matches)
            ai_reply += "\n\nİnceleyin, detay isterseniz yardımcı olabilirim! 😊"

    response.message(ai_reply)
    return str(response)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
