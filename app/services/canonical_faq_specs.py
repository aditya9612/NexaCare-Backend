"""Canonical hospital FAQ definitions — one row per topic with multilingual retrieval tags."""

from __future__ import annotations

from app.core.config import settings


def build_canonical_faq_specs() -> list[dict]:
    """Return canonical FAQ specs for a hospital (question/answer/tags/language)."""
    hours = settings.HOSPITAL_HOURS
    contact = settings.HOSPITAL_CONTACT
    location = settings.HOSPITAL_LOCATION
    name = settings.HOSPITAL_NAME

    return [
        {
            "topic": "opd",
            "language": "mr",
            "question": "OPD किती वाजता सुरू होते?",
            "answer": f"आमची OPD {hours} दरम्यान उपलब्ध आहे.",
            "tags": (
                "opd,timing,ओपीडी,OPD kiti vajta suru hote,OPD chi timing kay aahe,"
                "ओपीडीची वेळ काय आहे,OPD कधी सुरू होते,OPD timing काय आहे,"
                "What time does OPD start,When does OPD open,OPD start time,"
                "OPD kab shuru hota hai,OPD kab shuru hoti hai,OPD suru hote,"
                "ओपीडी किती वाजता सुरू होते,आज OPD सुरू आहे का,"
                "Is OPD open on Sunday,ravivari OPD aste ka,Ravivar ko OPD hota hai kya"
            ),
        },
        {
            "topic": "visiting",
            "language": "mr",
            "question": "भेट वेळ काय आहे?",
            "answer": f"भेट वेळ {hours} आहे.",
            "tags": (
                "visiting,hours,timing,visiting hours,भेट वेळ,भेट देण्याची वेळ,"
                "What are the visiting hours,What are hospital timings,"
                "hospital timings,hospital open time,रुग्णालयाची वेळ काय आहे,"
                "हॉस्पिटल किती वाजता उघडते,रुग्णाला भेटता येईल का"
            ),
        },
        {
            "topic": "parking",
            "language": "mr",
            "question": "पार्किंग उपलब्ध आहे का?",
            "answer": "हो, भेटकर्त्यांसाठी मोफत पार्किंग उपलब्ध आहे.",
            "tags": (
                "parking,available,parking aahe ka,Is parking available,"
                "Parking available aahe ka,पार्किंग,Char chaki parking aahe ka,"
                "free parking,parking facility"
            ),
        },
        {
            "topic": "insurance",
            "language": "mr",
            "question": "कॅशलेस इन्शुरन्स आहे का?",
            "answer": f"{name} मध्ये निवडक कॅशलेस इन्शुरन्स सुविधा उपलब्ध आहे. तपशीलांसाठी रिसेप्शनशी संपर्क साधा.",
            "tags": (
                "insurance,cashless,cashless insurance aahe ka,इन्शुरन्स,"
                "Is cashless insurance available,Cashless insurance available आहे का,"
                "Cashless insurance hai kya,insurance aahe ka,कॅशलेस"
            ),
        },
        {
            "topic": "emergency",
            "language": "mr",
            "question": "आपत्कालीन विभागाचा संपर्क काय आहे?",
            "answer": f"आपत्कालीन संपर्क: {contact}. Emergency सेवा २४ तास उपलब्ध आहे.",
            "tags": (
                "emergency,contact,आपत्कालीन,emergency contact,emergency contact number,"
                "Emergency सेवा आहे का,Do you provide emergency service,"
                "इमरजेंसी सेवा,emergency service 24x7"
            ),
        },
        {
            "topic": "emergency_dept",
            "language": "mr",
            "question": "आपत्कालीन विभाग किती वाजता उघड असतो?",
            "answer": "आपत्कालीन विभाग २४ तास उघडा असतो.",
            "tags": (
                "emergency,timing,department,आपत्कालीन विभाग,"
                "emergency department hours,emergency open 24 hours"
            ),
        },
        {
            "topic": "ambulance",
            "language": "mr",
            "question": "अॅम्ब्युलन्सचा नंबर काय आहे?",
            "answer": f"अॅम्ब्युलンスसाठी {contact} वर कॉल करा. रुग्णवाहिका सेवा २४ तास उपलब्ध आहे.",
            "tags": (
                "ambulance,number,अॅम्ब्युलन्स,ambulance number kay aahe,"
                "Is ambulance service available,रुग्णवाहिका,एम्बुलेंस"
            ),
        },
        {
            "topic": "doctor",
            "language": "mr",
            "question": "डॉक्टर उद्या उपलब्ध आहेत का?",
            "answer": "डॉक्टर उपलब्धता अपॉइंटमेंटनुसार बदलते. कृपया रिसेप्शनशी संपर्क साधा.",
            "tags": (
                "doctor,availability,udya,Doctor udya available aahet ka,डॉक्टर,"
                "Doctor Patil udya available aahet ka,डॉक्टर आज उपलब्ध आहेत का,"
                "doctor available today,specialist doctor"
            ),
        },
        {
            "topic": "appointment",
            "language": "mr",
            "question": "अपॉइंटमेंट कसे बुक करायचे?",
            "answer": f"अपॉइंटमेंट बुक करण्यासाठी {contact} वर कॉल करा किंवा रिसेप्शनला भेट द्या.",
            "tags": (
                "appointment,booking,अपॉइंटमेंट,How can I book an appointment,"
                "अपॉइंटमेंट कशी बुक करायची,online appointment,ऑनलाइन अपॉइंटमेंट"
            ),
        },
        {
            "topic": "cancellation",
            "language": "mr",
            "question": "अपॉइंटमेंट कसे रद्द करायचे?",
            "answer": f"अपॉइंटमेंट रद्द करण्यासाठी {contact} वर कॉल करा.",
            "tags": "appointment,cancel,cancellation,रद्द,cancel appointment",
        },
        {
            "topic": "billing",
            "language": "mr",
            "question": "बिलिंग काउंटर किती वाजता बंद होतो?",
            "answer": f"बिलिंग काउंटर {hours} दरम्यान उपलब्ध आहे. कार्ड, UPI आणि रोख पेमेंट स्वीकारले जाते.",
            "tags": (
                "billing,counter,band,बिलिंग,Billing counter kiti vajta band hoto,"
                "payment,UPI,card payment,Can I pay by card"
            ),
        },
        {
            "topic": "location",
            "language": "mr",
            "question": "रुग्णालय कुठे आहे?",
            "answer": f"आम्ही {location} येथे आहोत.",
            "tags": (
                "location,address,पत्ता,hospital location,Where is the hospital,"
                "हॉस्पिटल कुठे आहे,रुग्णालयाचा पत्ता काय आहे,hospital address"
            ),
        },
        {
            "topic": "contact",
            "language": "mr",
            "question": "तुमचा संपर्क क्रमांक काय आहे?",
            "answer": f"आमच्याशी {contact} वर संपर्क साधा.",
            "tags": (
                "contact,phone,number,संपर्क,How can I contact the hospital,"
                "contact number,hospital phone"
            ),
        },
        {
            "topic": "pharmacy",
            "language": "mr",
            "question": "फार्मसीची वेळ काय आहे?",
            "answer": f"फार्मसी {hours} दरम्यान उघडी असते.",
            "tags": (
                "pharmacy,timing,फार्मसी,फार्मसी आहे का,medical store,"
                "औषधांचे दुकान,medicine shop"
            ),
        },
        {
            "topic": "laboratory",
            "language": "mr",
            "question": "लॅबची वेळ काय आहे?",
            "answer": f"लॅब {hours} दरम्यान उपलब्ध आहे. ब्लड टेस्ट, X-Ray, MRI आणि CT Scan सुविधा उपलब्ध आहेत.",
            "tags": (
                "laboratory,lab,timing,लॅब,blood test,ब्लड टेस्ट,"
                "X-Ray,MRI,CT Scan,lab report,रिपोर्ट"
            ),
        },
    ]


CANONICAL_TOPICS = frozenset(spec["topic"] for spec in build_canonical_faq_specs())
