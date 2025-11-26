from flask import Flask, request, Response
import os
import requests
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# Gemini API Key ve endpoint (Railway Environment Variables)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_ENDPOINT = os.getenv("GEMINI_ENDPOINT", "https://api.gemini.com/v1/chat/completions")

# Tüm linkler
with open("links.txt", "r", encoding="utf-8") as f:
    ALL_URLS = [line.strip() for line in f if line.strip()]

# Desteklenen şehirler
CITIES = ["Adana", "Niğde", "Mersin", "Kahramanmaraş", "Hatay", "Gaziantep", "Osmaniye", "Kilis", "Aksaray"]

# Hafızada session
sessions = {}

def find_matches(filters):
    matches = []
    city = filters.get("city", "").lower()
    district = filters.get("district", "").lower()
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
        if service == "mehter" and detail and f"-{detail}." not in u:
            continue
        if service == "palyaco" and detail:
            if detail == "2-saat" and "2-saat" not in u:
                continue
            if detail == "tum-gun" and "tum-gun" not in u:
                continue
        matches.append(url)
    return matches[:3]

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    from_number = request.values.get("From")
    body = request.values.get("Body", "").strip().lower()

    if not from_number or not body:
        return "OK", 200

    if from_number not in sessions:
        sessions[from_number] = {"messages": [], "filters": {}}

    session = sessions[from_number]
    session["messages"].append({"role": "user", "content": body})
    filters = session["filters"]

    # Şehir tespiti
    for city in CITIES:
        if city.lower() in body:
            filters["city"] = city

    # İlçe tespiti
    known_districts = {url.split("/")[3].split("-")[1] for url in ALL_URLS if len(url.split("/")) > 3}
    for d in known_districts:
        if d.lower() in body:
            filters["district"] = d

    # Hizmet türü
    if "mehter" in body:
        filters["service_type"] = "mehter"
    elif "palyaço" in body or "palyaco" in body:
        filters["service_type"] = "palyaco"
    elif "dini düğün" in body or "sunnet" in body or "düğün" in body or "nikah" in body:
        filters["service_type"] = "sunnet_dugunu"
    elif "bando" in body:
        filters["service_type"] = "bando"
    elif "karagöz" in body or "gölge" in body or "hacivat" in body:
        filters["service_type"] = "karagoz"

    # Detay tespiti
    if filters.get("service_type") == "mehter":
        for size in ["8", "12", "18", "24", "30", "32"]:
            if size in body:
                filters["detail"] = size
                break
    if filters.get("service_type") == "palyaco":
        if "2 saat" in body or "2-saat" in body:
            filters["detail"] = "2-saat"
        elif "tüm gün" in body or "tum gun" in body:
            filters["detail"] = "tum-gun"

    # Gemini API çağrısı
    headers = {"Authorization": f"Bearer {GEMINI_API_KEY}", "Content-Type": "application/json"}
    try:
        data = {
            "model": "gemini-1.5",
            "messages": session["messages"],
            "temperature": 0.6,
            "max_tokens": 250
        }
        r = requests.post(GEMINI_ENDPOINT, headers=headers, json=data, timeout=10)
        r.raise_for_status()
        result = r.json()
        ai_reply = result.get("choices", [{}])[0].get("message", {}).get("content", "Cevap alınamadı.")
    except Exception as e:
        ai_reply = f"Hata Gemini API: {str(e)}"

    # Eğer bilgiler tamamsa link öner
    if filters.get("city") and filters.get("district") and filters.get("service_type") and \
       (filters["service_type"] not in ["mehter", "palyaco"] or filters.get("detail")):
        matches = find_matches(filters)
        if matches:
            ai_reply += "\n\nİşte uygun paketler:\n" + "\n".join(matches)

    session["messages"].append({"role": "assistant", "content": ai_reply})

    # Twilio cevabı
    resp = MessagingResponse()
    resp.message(ai_reply)
    return Response(str(resp), mimetype="application/xml")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
