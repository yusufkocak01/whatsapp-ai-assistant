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

            # Sadece il verilmişse -> merkez paketleri al
            if il and not ilce:
                for p in packages:
                    if normalize_city(p["il"]) == normalize_city(il) and "merkez" in normalize_city(p["ilce"]) and normalize_city(p["kategori"]) == normalize_city(target_category):
                        matches.append(p)
            # İl ve ilçe verilmişse -> o ilçe paketleri
            elif il and ilce:
                for p in packages:
                    if normalize_city(p["il"]) == normalize_city(il) and normalize_city(p["ilce"]) == normalize_city(ilce) and normalize_city(p["kategori"]) == normalize_city(target_category):
                        matches.append(p)

            if matches:
                response_text = f"✅ {target_category.title()} için şu linklere bakabilirsiniz. Bu paketlerde fiyat bilgisi de mevcut:\n\n"
                for p in matches[:5]:  # en fazla 5 paket
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
        # Kullanıcıya önce giriş cevabı göster
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
