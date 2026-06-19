"""
app/agent/llm.py
----------------
Groq LLM client using llama-3.3-70b-versatile.

Two extraction tasks:
  1. extract_patient_name()   — extracts name from free-form speech transcript
  2. extract_problem()        — extracts/normalises problem from free-form speech
  3. detect_specialty()       — maps problem to medical specialty
"""

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

logger = logging.getLogger("nexacare.agent.llm")

MODEL = "llama-3.3-70b-versatile"

VALID_SPECIALTIES = [
    "Cardiology", "Orthopedics", "Neurology", "Gastroenterology",
    "Dermatology", "Pulmonology", "ENT", "Gynecology", "Psychiatry",
    "Ophthalmology", "Endocrinology", "General Medicine",
    "Pediatrics", "Urology", "Nephrology",
]

SPECIALTY_KEYWORDS: dict[str, list[str]] = {
    "Cardiology":       ["heart", "chest pain", "palpitation", "cardiac", "blood pressure", "hypertension", "bp",
                          "छाती में दर्द", "हृदय", "रक्तदाब", "छातीत दुखणे", "हृदयविकार"],
    "Orthopedics":      ["bone", "joint", "knee", "back pain", "fracture", "spine", "shoulder", "hip", "arthritis",
                          "हड्डी", "घुटने में दर्द", "कमर दर्द", "जोड़ों का दर्द", "हाड", "गुडघेदुखी", "पाठदुखी", "सांधेदुखी"],
    "Neurology":        ["headache", "migraine", "seizure", "stroke", "numbness", "tremor", "dizziness", "memory",
                          "सिरदर्द", "चक्कर", "डोकेदुखी", "बेहोशी"],
    "Gastroenterology": ["stomach", "digestion", "acidity", "ibs", "liver", "nausea", "vomiting", "abdomen", "constipation",
                          "पेट दर्द", "उलटी", "अपचन", "पोटदुखी", "पोटात दुखणे", "जुलाब"],
    "Dermatology":      ["skin", "rash", "acne", "itching", "allergy", "eczema", "psoriasis", "hair loss",
                          "त्वचा", "खुजली", "चकत्ते", "त्वचेवर पुरळ", "खाज"],
    "Pulmonology":      ["breathing", "lungs", "cough", "asthma", "breathless", "wheezing", "copd",
                          "खांसी", "सांस लेने में तकलीफ", "खोकला", "दम लागणे", "श्वास घेण्यास त्रास"],
    "ENT":              ["ear", "nose", "throat", "hearing", "tonsil", "sinus", "cold", "sneezing",
                          "कान में दर्द", "गला खराब", "कानदुखी", "घसा खवखवणे", "सर्दी"],
    "Gynecology":       ["periods", "menstrual", "pregnancy", "pcod", "pcos", "uterus", "ovary",
                          "मासिक धर्म", "गर्भावस्था", "मासिक पाळी", "गर्भधारणा"],
    "Psychiatry":       ["anxiety", "depression", "stress", "mental", "sleep", "insomnia", "panic", "mood",
                          "तनाव", "नींद नहीं आना", "ताण", "झोप न लागणे", "चिंता"],
    "Ophthalmology":    ["eye", "vision", "blur", "glasses", "cataract", "retina",
                          "आंख में दर्द", "धुंधला दिखना", "डोळ्यात दुखणे", "डोळ्यांचा त्रास"],
    "Endocrinology":    ["thyroid", "diabetes", "sugar", "hormones", "weight gain", "fatigue", "insulin",
                          "मधुमेह", "थकान", "थायराइड", "साखर", "थकवा"],
    "Pediatrics":       ["child", "baby", "infant", "kids", "fever in child", "vaccination",
                          "बच्चा", "मूल", "बच्चे को बुखार"],
    "Urology":          ["urinary", "kidney stone", "prostate", "urine", "bladder", "uti",
                          "पेशाब में जलन", "लघवीला त्रास", "पथरी"],
    "Nephrology":       ["kidney", "renal", "dialysis", "creatinine", "kidney failure",
                          "किडनी", "डायलिसिस"],
}


def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set in environment")
    return Groq(api_key=api_key)


def _keyword_hint(problem: str) -> Optional[str]:
    problem_lower = problem.lower()
    for specialty, keywords in SPECIALTY_KEYWORDS.items():
        if any(kw in problem_lower for kw in keywords):
            return specialty
    return None


# ── 1. Name extraction ────────────────────────────────────────────────────────

NAME_SYSTEM_PROMPT = """You are a medical receptionist assistant for an Indian hospital.
The patient was asked "Please say your full name." and you received their speech transcript.

The patient may have spoken in English, Hindi, or Marathi. The transcript may
contain Devanagari script (Hindi/Marathi), Latin script (English or
transliterated Hindi/Marathi), or a mix. Filler phrases meaning "my name is"
appear in all three languages — for example "my name is", "mera naam hai",
"माझे नाव आहे", "मेरा नाम है" — strip these in whichever language they appear.

Your job: extract ONLY the patient's actual name from the transcript.

Rules:
- Respond ONLY with valid JSON. No markdown, no explanation outside JSON.
- Remove filler phrases (in English, Hindi, or Marathi) like "my name is",
  "I am", "this is", "myself", "call me", "मेरा नाम है", "माझे नाव आहे", etc.
- If a clear name is present, extract it properly capitalised (if in Latin
  script) or as correctly written (if in Devanagari script).
- If the transcript is too unclear, empty, or does not contain a name, set found to false.
- Names can be Indian names — be flexible. A single short word can be a valid name.

JSON format:
{
  "found": true or false,
  "name": "<extracted name or empty string if not found>",
  "confidence": "<high|medium|low>",
  "reason": "<one short sentence>"
}"""


def extract_patient_name(transcript: str, twilio_confidence: float = -1.0) -> dict:
    """
    Use Groq LLM to extract the patient's name from a speech transcript.

    twilio_confidence: the raw Twilio STT confidence value (0.0–1.0).
    Twilio frequently reports 0.0 even on correct transcripts, so we NEVER
    reject a transcript based on confidence alone — we always try the LLM.

    Returns:
        {
            "found": bool,
            "name": str,
            "confidence": "high"|"medium"|"low",
            "reason": str
        }
    """
    if not transcript or not transcript.strip():
        return {"found": False, "name": "", "confidence": "low", "reason": "Empty transcript."}

    # Log for debugging — useful to track which transcripts fail extraction
    logger.info(
        f"Name extraction attempt | transcript={transcript!r} | "
        f"twilio_confidence={twilio_confidence}"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": NAME_SYSTEM_PROMPT},
                {"role": "user",   "content": f'Transcript: "{transcript.strip()}"'},
            ],
            temperature=0.0,   # deterministic — name extraction is not creative
            max_tokens=100,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        # Sanitise response
        if not isinstance(result.get("found"), bool):
            result["found"] = bool(result.get("name", "").strip())
        if not result.get("name", "").strip():
            result["found"] = False
            result["name"] = ""

        logger.info(
            f"Name extraction: found={result['found']} name={result.get('name')!r} "
            f"conf={result.get('confidence')} | {result.get('reason')}"
        )
        return result

    except Exception as e:
        logger.warning(f"Name extraction LLM failed: {e} — using fallback")
        # Graceful fallback — basic prefix stripping across EN/HI/MR
        raw = transcript.strip()
        prefixes = [
            "my name is ", "i am ", "this is ", "myself ", "name is ", "i'm ", "call me ",
            "मेरा नाम है ", "मेरा नाम ", "मैं हूँ ", "माझे नाव आहे ", "माझे नाव ", "मी आहे ",
        ]
        clean = raw.lower()
        for prefix in prefixes:
            if clean.startswith(prefix.lower()):
                raw = raw[len(prefix):]
                break
        name = raw.strip().title()
        if len(name.replace(" ", "")) >= 2:
            return {"found": True, "name": name, "confidence": "low", "reason": "Fallback prefix strip."}
        return {"found": False, "name": "", "confidence": "low", "reason": f"LLM error: {str(e)[:60]}"}


# ── 2. Problem extraction ─────────────────────────────────────────────────────

PROBLEM_SYSTEM_PROMPT = """You are a medical receptionist assistant for an Indian hospital.
The patient was asked "Please describe your health problem or symptoms."

The patient may have spoken in English, Hindi, or Marathi. The transcript may
contain Devanagari script (Hindi/Marathi), Latin script (English or
transliterated Hindi/Marathi), or a mix.

Your job: extract and normalise the medical problem from the transcript.

Rules:
- Respond ONLY with valid JSON. No markdown, no explanation outside JSON.
- Rephrase vague or broken speech into a clear medical problem description.
- IMPORTANT: write the cleaned "problem" in the SAME language the patient
  spoke (Hindi stays in Hindi/Devanagari, Marathi stays in Marathi/Devanagari,
  English stays in English). This text gets read back to the patient by
  text-to-speech in their own language, so do not translate it.
- If the patient described a clear problem, set found to true.
- If the transcript is too unclear, too short (just "pain" with no context),
  or does not describe any health problem, set found to false.
- Be generous — if there's any health information, extract it, regardless of language.

JSON format:
{
  "found": true or false,
  "problem": "<cleaned medical problem description, in the patient's spoken language, or empty string>",
  "confidence": "<high|medium|low>",
  "reason": "<one short sentence>"
}"""


def extract_problem(transcript: str, twilio_confidence: float = -1.0) -> dict:
    """
    Use Groq LLM to extract and normalise the patient's problem from transcript.

    twilio_confidence: raw Twilio STT score. Never used to reject a transcript.

    Returns:
        {
            "found": bool,
            "problem": str,
            "confidence": "high"|"medium"|"low",
            "reason": str
        }
    """
    if not transcript or not transcript.strip():
        return {"found": False, "problem": "", "confidence": "low", "reason": "Empty transcript."}

    logger.info(
        f"Problem extraction attempt | transcript={transcript!r} | "
        f"twilio_confidence={twilio_confidence}"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PROBLEM_SYSTEM_PROMPT},
                {"role": "user",   "content": f'Transcript: "{transcript.strip()}"'},
            ],
            temperature=0.0,   # deterministic extraction
            max_tokens=150,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content.strip())

        if not isinstance(result.get("found"), bool):
            result["found"] = bool(result.get("problem", "").strip())
        if not result.get("problem", "").strip():
            result["found"] = False
            result["problem"] = ""

        logger.info(
            f"Problem extraction: found={result['found']} "
            f"conf={result.get('confidence')} | {result.get('reason')}"
        )
        return result

    except Exception as e:
        logger.warning(f"Problem extraction LLM failed: {e} — using raw transcript as fallback")
        # If LLM fails entirely, use raw transcript if it's long enough to be meaningful
        problem = transcript.strip()
        if len(problem.replace(" ", "")) >= 4:
            return {"found": True, "problem": problem, "confidence": "low", "reason": "LLM error — raw transcript used."}
        return {"found": False, "problem": "", "confidence": "low", "reason": f"LLM error: {str(e)[:60]}"}


# ── 3. Specialty detection ────────────────────────────────────────────────────

SPECIALTY_SYSTEM_PROMPT = f"""You are a medical triage assistant for NexaCare hospital.
Analyse the patient's problem and return the most appropriate medical specialty.

The problem description may be written in English, Hindi, or Marathi
(Devanagari or Latin script). Understand it regardless of language.

Available specialties:
{chr(10).join(f"- {s}" for s in VALID_SPECIALTIES)}

Rules:
- Respond ONLY with a valid JSON object. No markdown, no preamble.
- If unsure, use General Medicine.
- Be conservative: prefer common conditions over rare ones.

JSON format:
{{
  "specialty": "<one of the specialties above>",
  "confidence": "<high|medium|low>",
  "reasoning": "<one short sentence>"
}}"""


def detect_specialty(problem_description: str) -> dict:
    """
    Detect medical specialty from patient's cleaned problem description.
    """
    hint = _keyword_hint(problem_description)

    user_prompt = (
        f'Patient problem: "{problem_description}"\n\n'
        + (f'Keyword hint: "{hint}". Confirm or override based on full context.\n\n' if hint else "")
        + "Respond ONLY with the JSON object."
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SPECIALTY_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=150,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content.strip())

        if result.get("specialty") not in VALID_SPECIALTIES:
            result["specialty"] = hint or "General Medicine"
            result["confidence"] = "low"
            result["reasoning"] = "Specialty not recognised — routing to General Medicine."

        logger.info(
            f"Specialty: {result['specialty']} ({result['confidence']}) | {result['reasoning']}"
        )
        return result

    except Exception as e:
        logger.warning(f"Specialty detection LLM failed: {e} — using keyword hint")
        return {
            "specialty": hint or "General Medicine",
            "confidence": "low",
            "reasoning": "AI analysis unavailable — keyword fallback used.",
        }