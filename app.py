from flask import Flask, request
import os
import re
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Ham link listesi
with open("links.txt", "r", encoding="utf-8") as f:
    ALL_URLS = [line.strip() for line in f if line.strip()]

# Desteklenen iller
CITIES = ["Adana", "Niğde", "Mersin", "Kahramanmaraş", "Hatay", "Gaziantep", "Osmaniye", "Kilis", "Aksaray"]

# Oturum saklama (üretimde Redis önerilir)
sessions = {}

def find_matching_urls(filters):
    matches = []
    city = filters.get("city", "").lower() if filters.get("city") else ""
    district = filters.get("district", "").lower() if filters.get("district") else ""
    service = filters.get("service_type")
    detail = filters.get("detail")

    for url in ALL_URLS:
        url_lower = url.lower()

        # İl kontrolü
        if city and not url_lower.startswith(f"https://israorganizasyon.com/{city.lower()}"):
            continue

        # İlçe kontrolü
        if district:
            parts = url.replace("https://israorganizasyon.com/", "").split("-")
            if len(parts) < 2:
                continue
            url_district = parts[1].lower()
            if district not in url_district and url_district not in district:
                continue

        # Hizmet türü
        if service == "mehter" and "mehter" not in url_lower:
            continue
        if service == "palyaco" and "palyaco" not in url_lower:
            continue
        if service in ["sunnet_dugunu", "dini_dugun"] and not ("sunnet" in url_lower or "dugunu" in url_lower):
            continue
        if service == "bando" and "bando" not in url_lower:
            continue
        if service == "karagoz" and ("karagoz" not in url_lower and "golge" not in url_lower):
            continue

        # Detay kontrolü
        if service == "mehter" and detail:
            if f"-{detail}." not in url_lower:
                continue
        if service == "palyaco" and detail:
            if detail == "2-saat" and "2-saat" not in url_lower:
                continue
            if detail == "tum-gun" and "tum-gun" not in url_lower:
                continue

        matches.append(url)

    return matches[:3]

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    from_number = request.values.get("From")
    incoming_msg = request.values.get("Body", "").strip()

    if not from_number:
        return "OK", 200

    if from_number not in sessions:
        sessions[from_number] = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Sen, İsra Organizasyon’un samimi ve profesyonel WhatsApp asistanısın. "
                        "Görevin: müşteriden sırayla şunları doğal bir şekilde öğrenmek:\n"
                        "1. Hangi ilde olduğunu,\n"
                        "2. Hangi ilçede hizmet istediğini,\n"
                        "3. Hangi hizmet türünü (örneğin: mehter, palyaço, dini düğün/sunnet, bando, karagöz),\n"
                        "4. Gerekirse detay: mehter için kaç kişilik, palyaço için 2 saat mi tüm gün mü?\n"
                        "Yanıtlar kısa, doğal, Türkçe ve her zaman samimi olmalı. "
                        "Link önerdiğinde sadece URL'leri yaz, açıklamayı önceki cümlede ver. "
                        "Asla tahminle link önerme. Sadece kesin bilgi olduğunda öner."
                    )
                }
            ],
            "filters": {}
        }

    session = sessions[from_number]
    session["messages"].append({"role": "user", "content": incoming_msg})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=session["messages"],
            temperature=0.6,
            max_tokens=250
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        ai_reply = "Anlamsız bir hata oluştu. Lütfen tekrar yazın."

    session["messages"].append({"role": "assistant", "content": ai_reply})

    # Basit metin analiziyle filtreleme
    text = incoming_msg.lower()
    filters = session["filters"]

    for city in CITIES:
        if city.lower() in text:
            filters["city"] = city

    # İlçe adları URL’lerden çıkarılabilir, ancak burada sadece bazıları elle eşleştirildi
    # Daha gelişmiş sistem için ilçe listesi de çıkarılabilir
    possible_districts = set()
    for url in ALL_URLS:
        parts = url.replace("https://israorganizasyon.com/", "").split("-")
        if len(parts) >= 2:
            possible_districts.add(parts[1].lower())
    for dist in possible_districts:
        if dist in text:
            filters["district"] = dist.title()

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
        if "8" in text: filters["detail"] = "8"
        elif "12" in text: filters["detail"] = "12"
        elif "18" in text: filters["detail"] = "18"
        elif "24" in text: filters["detail"] = "24"
        elif "30" in text: filters["detail"] = "30"
        elif "32" in text: filters["detail"] = "32"

    if filters.get("service_type") == "palyaco":
        if "2 saat" in text or "2-saat" in text:
            filters["detail"] = "2-saat"
        elif "tüm gün" in text or "tum gun" in text:
            filters["detail"] = "tum-gun"

    # Link önerme
    if (
        filters.get("city") and
        filters.get("district") and
        filters.get("service_type") and
        (
            filters["service_type"] not in ["mehter", "palyaco"] or
            filters.get("detail")
        )
    ):
        matching_links = find_matching_urls(filters)
        if matching_links and "http" not in ai_reply:
            ai_reply += "\n\nİşte size uygun paketler:\n" + "\n".join(matching_links)
            ai_reply += "\n\nİnceleyin, beğendiğiniz varsa detay verebilirim! 😊"

    return ai_reply, 200, {"Content-Type": "text/plain; charset=utf-8"}

# Railway portunu kullan, yoksa 8080
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
