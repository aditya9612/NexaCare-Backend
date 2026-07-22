from app.core.config import settings

HOSPITAL_NAME = "Nexa Care Hospital"


def greeting(language: str) -> str:
    messages = {
        "en": (
            f"Hello, welcome to {HOSPITAL_NAME}. "
            "I am Nexa Care Hospital assistant. How may I help you today?"
        ),
        "hi": (
            f"नमस्ते, {HOSPITAL_NAME} में आपका स्वागत है। "
            "मैं नेक्सा केयर हॉस्पिटल असिस्टेंट हूँ। मैं आपकी कैसे सहायता कर सकती हूँ?"
        ),
        "mr": (
            f"नमस्कार, {HOSPITAL_NAME} मध्ये आपले स्वागत आहे. "
            "मी नेक्सा केअर हॉस्पिटल असिस्टंट आहे. मी आपली कशी मदत करू शकते?"
        ),
    }
    return messages.get(language, messages["en"])


def intent_menu(language: str) -> str:
    messages = {
        "en": (
            "Press 1 to book an appointment, 2 to reschedule, 3 to cancel, "
            "4 to talk to reception, or 5 for hospital information. "
            "You can also ask about doctor availability."
        ),
        "hi": (
            "अपॉइंटमेंट बुक के लिए 1, बदलने के लिए 2, रद्द के लिए 3, "
            "रिसेप्शन के लिए 4, या अस्पताल जानकारी के लिए 5 दबाएँ।"
        ),
        "mr": (
            "अपॉइंटमेंट बुक करण्यासाठी 1, बदलण्यासाठी 2, रद्द करण्यासाठी 3, "
            "रिसेप्शनसाठी 4, किंवा रुग्णालय माहितीसाठी 5 दाबा."
        ),
    }
    return messages.get(language, messages["en"])


def ask_faq_question(language: str) -> str:
    return {
        "en": "Please ask your question about hospital timings, location, contact, or policies.",
        "hi": "कृपया अस्पताल के समय, स्थान, संपर्क या नीतियों के बारे में अपना प्रश्न पूछें।",
        "mr": "कृपया रुग्णालयाची वेळ, स्थान, संपर्क किंवा धोरणांबद्दल तुमचा प्रश्न विचारा.",
    }.get(language, "Please ask your hospital question.")


def transferring_to_reception(language: str) -> str:
    return {
        "en": "Please wait while I connect you to reception.",
        "hi": "कृपया प्रतीक्षा करें, मैं आपको रिसेप्शन से जोड़ रही हूँ।",
        "mr": "कृपया थांबा, मी तुम्हाला रिसेप्शनशी जोडत आहे.",
    }.get(language, "Please wait while I connect you to reception.")


def ask_patient_name(language: str) -> str:
    return {
        "en": "May I have your full name please?",
        "hi": "कृपया अपना पूरा नाम बताइए।",
        "mr": "कृपया आपले पूर्ण नाव सांगा.",
    }.get(language, "May I have your full name please?")


def ask_doctor(language: str) -> str:
    return {
        "en": "Which doctor or department would you like? For example, cardiologist or general physician.",
        "hi": "आप किस डॉक्टर या विभाग से मिलना चाहेंगे? जैसे हृदय रोग विशेषज्ञ या सामान्य चिकित्सक।",
        "mr": "आपला कोणता डॉक्टर किंवा विभाग हवा आहे? उदा. हृदयरोग तज्ञ किंवा सामान्य वैद्य.",
    }.get(language, "Which doctor or department would you like?")


def ask_symptoms(language: str) -> str:
    return {
        "en": "Please tell me briefly about your symptoms or health issue.",
        "hi": "कृपया अपने लक्षण या स्वास्थ्य समस्या संक्षेप में बताइए।",
        "mr": "कृपया आपले लक्षणे किंवा आरोग्य समस्या थोडक्यात सांगा.",
    }.get(language, "Please tell me briefly about your symptoms.")


def ask_date(language: str) -> str:
    return {
        "en": "What date would you prefer for the appointment?",
        "hi": "आप किस तारीख को अपॉइंटमेंट चाहेंगे?",
        "mr": "आपल्याला कोणत्या तारखेला अपॉइंटमेंट हवी आहे?",
    }.get(language, "What date would you prefer?")


def ask_time(language: str) -> str:
    return {
        "en": "What time would you prefer?",
        "hi": "आप किस समय आना चाहेंगे?",
        "mr": "आपल्याला कोणत्या वेळेस यायचे आहे?",
    }.get(language, "What time would you prefer?")


def ask_mobile(language: str) -> str:
    return {
        "en": "Please tell me your mobile number.",
        "hi": "कृपया अपना मोबाइल नंबर बताइए।",
        "mr": "कृपया आपला मोबाइल नंबर सांगा.",
    }.get(language, "Please tell me your mobile number.")


def confirmation_summary(state, language: str) -> str:
    lines_en = (
        f"Patient Name: {state.patient_name}. "
        f"Doctor or Department: {state.doctor_or_department}. "
        f"Date: {state.appointment_date}. "
        f"Time: {state.appointment_time}. "
        f"Mobile Number: {state.mobile_number}. "
        "Should I confirm this appointment?"
    )
    lines_hi = (
        f"मरीज का नाम: {state.patient_name}. "
        f"डॉक्टर या विभाग: {state.doctor_or_department}. "
        f"तारीख: {state.appointment_date}. "
        f"समय: {state.appointment_time}. "
        f"मोबाइल नंबर: {state.mobile_number}. "
        "क्या मैं यह अपॉइंटमेंट कन्फर्म करूँ?"
    )
    lines_mr = (
        f"रुग्णाचे नाव: {state.patient_name}. "
        f"डॉक्टर किंवा विभाग: {state.doctor_or_department}. "
        f"तारीख: {state.appointment_date}. "
        f"वेळ: {state.appointment_time}. "
        f"मोबाइल नंबर: {state.mobile_number}. "
        "मी ही अपॉइंटमेंट कन्फर्म करू?"
    )
    return {"en": lines_en, "hi": lines_hi, "mr": lines_mr}.get(language, lines_en)


def booking_success(language: str) -> str:
    return {
        "en": "Your appointment has been booked successfully. Thank you for calling Nexa Care Hospital. Goodbye.",
        "hi": "आपका अपॉइंटमेंट सफलतापूर्वक बुक हो गया है। नेक्सा केयर हॉस्पिटल को कॉल करने के लिए धन्यवाद। अलविदा।",
        "mr": "आपली अपॉइंटमेंट यशस्वीरित्या बुक झाली आहे. नेक्सा केअर हॉस्पिटलला कॉल केल्याबद्दल धन्यवाद. नमस्कार.",
    }.get(language, "Your appointment has been booked successfully.")


def cancel_success(language: str) -> str:
    return {
        "en": "Your appointment has been cancelled successfully. Goodbye.",
        "hi": "आपका अपॉइंटमेंट सफलतापूर्वक रद्द कर दिया गया है। अलविदा।",
        "mr": "आपली अपॉइंटमेंट यशस्वीरित्या रद्द करण्यात आली आहे. नमस्कार.",
    }.get(language, "Your appointment has been cancelled successfully.")


def reschedule_success(language: str) -> str:
    return {
        "en": "Your appointment has been rescheduled successfully. Goodbye.",
        "hi": "आपका अपॉइंटमेंट सफलतापूर्वक बदल दिया गया है। अलविदा।",
        "mr": "आपली अपॉइंटमेंट यशस्वीरित्या बदलण्यात आली आहे. नमस्कार.",
    }.get(language, "Your appointment has been rescheduled successfully.")


def slot_unavailable(language: str, alt1: str, alt2: str) -> str:
    return {
        "en": f"The requested time is unavailable. Would you like {alt1} or {alt2} instead?",
        "hi": f"यह समय उपलब्ध नहीं है। क्या आप {alt1} या {alt2} चाहेंगे?",
        "mr": f"ही वेळ उपलब्ध नाही. आपल्याला {alt1} किंवा {alt2} हवे आहे का?",
    }.get(language, f"The requested time is unavailable. Would you like {alt1} or {alt2} instead?")


def repeat_slowly(language: str) -> str:
    return {
        "en": "Could you please repeat slowly?",
        "hi": "कृपया धीरे-धीरे दोहराएं?",
        "mr": "कृपया हळूहळू पुन्हा सांगाल का?",
    }.get(language, "Could you please repeat slowly?")


def could_not_hear(language: str) -> str:
    return {
        "en": "I could not hear properly. Could you please repeat?",
        "hi": "मुझे ठीक से सुनाई नहीं दिया। कृपया दोहराएं?",
        "mr": "मला नीट ऐकू आले नाही. कृपया पुन्हा सांगा?",
    }.get(language, "I could not hear properly. Could you please repeat?")


def hospital_info(language: str) -> str:
    return {
        "en": (
            f"{settings.HOSPITAL_NAME} is open {settings.HOSPITAL_HOURS}. "
            f"Location: {settings.HOSPITAL_LOCATION}. Contact: {settings.HOSPITAL_CONTACT}."
        ),
        "hi": (
            f"{settings.HOSPITAL_NAME} {settings.HOSPITAL_HOURS} खुला रहता है। "
            f"पता: {settings.HOSPITAL_LOCATION}. संपर्क: {settings.HOSPITAL_CONTACT}."
        ),
        "mr": (
            f"{settings.HOSPITAL_NAME} {settings.HOSPITAL_HOURS} उघडे असते. "
            f"पत्ता: {settings.HOSPITAL_LOCATION}. संपर्क: {settings.HOSPITAL_CONTACT}."
        ),
    }.get(language, f"Hours: {settings.HOSPITAL_HOURS}.")


def pending_callback(language: str) -> str:
    return {
        "en": "Your request has been received. Our team will call you shortly to confirm. Goodbye.",
        "hi": "आपका अनुरोध प्राप्त हो गया है। हमारी टीम जल्द ही पुष्टि के लिए कॉल करेगी। अलविदा।",
        "mr": "आपली विनंती मिळाली आहे. आमची टीम लवकरच पुष्टीसाठी कॉल करेल. नमस्कार.",
    }.get(language, "Your request has been received. Our team will call you shortly.")
