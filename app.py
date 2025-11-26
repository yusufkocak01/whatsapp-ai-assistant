from flask import Flask, request
import os
import re
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Load all URLs
with open("links.txt", "r", encoding="utf-8") as f:
    ALL_URLS = [line.strip() for line in f if line.strip()]

# Supported cities
CITIES = ["Adana", "Niğde", "Mersin", "Kahramanmaraş", "Hatay", "Gaziantep", "Osmaniye", "Kilis", "Aksaray"]

# In-memory sessions (use Redis in production)
sessions = {}

def find_matches(filters):
    matches = []
    city = filters.get("city", "").lower() if filters.get("city") else ""
    district = filters.get("district", "").lower() if filters.get("district") else ""
    service = filters.get("service_type")
    detail = filters.get("detail")  # mehter size or palyaco duration

    for url in ALL_URLS:
        u = url.lower()

        # City filter
        if city and not u.startswith(f"https://israorganizasyon.com/{city.lower()}"):
            continue

        # District filter
        if district:
            parts = url.replace("https://israorganizasyon.com/", "").split("-")
            if len(parts) < 2:
                continue
            if district not in parts[1].lower():
                continue

        # Service type
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

        # Detail filter
        if service == "mehter" and detail:
            if f"-{detail}." not in u:
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
    body = request.values.get("Body", "").strip()

    if not from_number:
        return "OK", 200

    if from_number not in sessions:
        sessions[from_number] = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Sen, İsra Organizasyon’un samimi WhatsApp asistanısın. "
                        "Müşteriden doğal sorularla şunları öğren:\n"
                        "1. İl (Adana, Niğde, vs.)\n"
                        "2. İlçe\n"
                        "3. Hizmet (mehter, palyaço, dini düğün/sunnet, bando, karagöz)\n"
                        "4. Detay (mehter: kişi sayısı; palyaço: 2 saat veya tüm gün)\n"
                        "Sadece tam bilgi olduğunda uygun link(leri) öner. "
                        "Yanıtlar kısa, Türkçe ve samimi olsun. Tahminle link önerme."
                    )
                }
            ],
            "filters": {}
        }

    session = sessions[from_number]
    session["messages"].append({"role": "user", "content": body})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=session["messages"],
            temperature=0.6,
            max_tokens=250
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        ai_reply = "Anlaşılmadı. Lütfen tekrar yazar mısınız?"

    session["messages"].append({"role": "assistant", "content": ai_reply})

    # Extract info from user message
    text = body.lower()
    filters = session["filters"]

    for city in CITIES:
        if city.lower() in text:
            filters["city"] = city

    # Extract district from known list
    known_districts = {url.split("/")[3].split("-")[1] for url in ALL_URLS if len(url.split("/")) > 3}
    for d in known_districts:
        if d.lower() in text:
            filters["district"] = d

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

    # Suggest links only when all needed info is present
    if (
        filters.get("city") and
        filters.get("district") and
        filters.get("service_type") and
        (filters["service_type"] not in ["mehter", "palyaco"] or filters.get("detail"))
    ):
        matches = find_matches(filters)
        if matches and "http" not in ai_reply:
            ai_reply += "\n\nİşte size uygun paketler:\n" + "\n".join(matches)
            ai_reply += "\n\nİnceleyin, detay isterseniz yardımcı olabilirim! 😊"

    return ai_reply, 200, {"Content-Type": "text/plain; charset=utf-8"}

# Run on Railway-compatible port
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
