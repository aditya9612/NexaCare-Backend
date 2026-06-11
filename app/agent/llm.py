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
    "Cardiology":       ["heart", "chest pain", "palpitation", "cardiac", "blood pressure", "hypertension", "bp"],
    "Orthopedics":      ["bone", "joint", "knee", "back pain", "fracture", "spine", "shoulder", "hip", "arthritis"],
    "Neurology":        ["headache", "migraine", "seizure", "stroke", "numbness", "tremor", "dizziness", "memory"],
    "Gastroenterology": ["stomach", "digestion", "acidity", "ibs", "liver", "nausea", "vomiting", "abdomen", "constipation"],
    "Dermatology":      ["skin", "rash", "acne", "itching", "allergy", "eczema", "psoriasis", "hair loss"],
    "Pulmonology":      ["breathing", "lungs", "cough", "asthma", "breathless", "wheezing", "copd"],
    "ENT":              ["ear", "nose", "throat", "hearing", "tonsil", "sinus", "cold", "sneezing"],
    "Gynecology":       ["periods", "menstrual", "pregnancy", "pcod", "pcos", "uterus", "ovary"],
    "Psychiatry":       ["anxiety", "depression", "stress", "mental", "sleep", "insomnia", "panic", "mood"],
    "Ophthalmology":    ["eye", "vision", "blur", "glasses", "cataract", "retina"],
    "Endocrinology":    ["thyroid", "diabetes", "sugar", "hormones", "weight gain", "fatigue", "insulin"],
    "Pediatrics":       ["child", "baby", "infant", "kids", "fever in child", "vaccination"],
    "Urology":          ["urinary", "kidney stone", "prostate", "urine", "bladder", "uti"],
    "Nephrology":       ["kidney", "renal", "dialysis", "creatinine", "kidney failure"],
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

NAME_SYSTEM_PROMPT = """You are a medical receptionist assistant.
The patient was asked "Please say your full name." and you received their speech transcript.

Your job: extract ONLY the patient's actual name from the transcript.

Rules:
- Respond ONLY with valid JSON. No markdown, no explanation outside JSON.
- Remove filler phrases like "my name is", "I am", "this is", "myself", "call me", etc.
- If a clear name is present, extract it properly capitalised.
- If the transcript is too unclear, empty, or does not contain a name, set found to false.
- Names can be Indian names — be flexible.

JSON format:
{
  "found": true or false,
  "name": "<extracted name or empty string if not found>",
  "confidence": "<high|medium|low>",
  "reason": "<one short sentence>"
}"""


def extract_patient_name(transcript: str) -> dict:
    """
    Use Groq LLM to extract the patient's name from a speech transcript.

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

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": NAME_SYSTEM_PROMPT},
                {"role": "user",   "content": f'Transcript: "{transcript.strip()}"'},
            ],
            temperature=0.1,
            max_tokens=100,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content.strip())

        # Validate
        if not isinstance(result.get("found"), bool):
            result["found"] = bool(result.get("name", "").strip())
        if not result.get("name"):
            result["found"] = False

        logger.info(
            f"Name extraction: found={result['found']} name={result.get('name')!r} "
            f"conf={result.get('confidence')} | {result.get('reason')}"
        )
        return result

    except Exception as e:
        logger.warning(f"Name extraction LLM failed: {e}")
        # Graceful fallback — basic prefix stripping
        raw = transcript.strip().lower()
        for prefix in ["my name is ", "i am ", "this is ", "myself ", "name is ", "i'm ", "call me "]:
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        name = raw.strip().title()
        if len(name) >= 2:
            return {"found": True, "name": name, "confidence": "low", "reason": "Fallback prefix strip."}
        return {"found": False, "name": "", "confidence": "low", "reason": f"LLM error: {str(e)[:60]}"}


# ── 2. Problem extraction ─────────────────────────────────────────────────────

PROBLEM_SYSTEM_PROMPT = """You are a medical receptionist assistant.
The patient was asked "Please describe your health problem or symptoms."

Your job: extract and normalise the medical problem from the transcript.

Rules:
- Respond ONLY with valid JSON. No markdown, no explanation outside JSON.
- Rephrase vague or broken speech into a clear medical problem description.
- If the patient described a clear problem, set found to true.
- If the transcript is too unclear, too short (just "pain" with no context), 
  or does not describe any health problem, set found to false.
- Be generous — if there's any health information, extract it.

JSON format:
{
  "found": true or false,
  "problem": "<cleaned medical problem description or empty string>",
  "confidence": "<high|medium|low>",
  "reason": "<one short sentence>"
}"""


def extract_problem(transcript: str) -> dict:
    """
    Use Groq LLM to extract and normalise the patient's problem from transcript.

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

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PROBLEM_SYSTEM_PROMPT},
                {"role": "user",   "content": f'Transcript: "{transcript.strip()}"'},
            ],
            temperature=0.1,
            max_tokens=150,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content.strip())

        if not isinstance(result.get("found"), bool):
            result["found"] = bool(result.get("problem", "").strip())

        logger.info(
            f"Problem extraction: found={result['found']} "
            f"conf={result.get('confidence')} | {result.get('reason')}"
        )
        return result

    except Exception as e:
        logger.warning(f"Problem extraction LLM failed: {e}")
        problem = transcript.strip()
        if len(problem) >= 5:
            return {"found": True, "problem": problem, "confidence": "low", "reason": f"LLM error — raw transcript used."}
        return {"found": False, "problem": "", "confidence": "low", "reason": f"LLM error: {str(e)[:60]}"}


# ── 3. Specialty detection ────────────────────────────────────────────────────

SPECIALTY_SYSTEM_PROMPT = f"""You are a medical triage assistant for NexaCare hospital.
Analyse the patient's problem and return the most appropriate medical specialty.

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