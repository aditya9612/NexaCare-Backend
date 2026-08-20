"""
app/agent/llm.py
----------------
LLM client for NexaCare AI Voice Agent.

Primary: Google Gemini (GEMINI_API_KEY).
Fallback: OpenAI (OPENAI_API_KEY) when Gemini fails or is not configured.

Used for:
  1. extract_patient_name()   — extracts name from free-form speech transcript
  2. extract_problem()        — extracts/normalises problem + severity from speech
  3. detect_specialty()       — maps problem to medical specialty with confidence
"""

import json
import logging
from enum import Enum
from typing import Optional, Type, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types
except ImportError as exc:
    raise ImportError(
        "google-genai package is required for the experimental voice agent LLM"
    ) from exc

load_dotenv()

logger = logging.getLogger("nexacare.agent.llm")

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

_GEMINI_PLACEHOLDER_KEYS = frozenset({
    "",
    "REPLACE_WITH_GEMINI_KEY",
    "your_gemini_api_key",
    "changeme",
})


# ── Configuration ─────────────────────────────────────────────────────────────

def _get_model() -> str:
    """Get Gemini model name from settings."""
    from app.core.config import settings
    return settings.GEMINI_MODEL or "gemini-2.5-flash"


def _get_openai_model() -> str:
    """Get OpenAI model name from settings."""
    from app.core.config import settings
    return settings.OPENAI_MODEL or "gpt-4o-mini"


def _gemini_api_key() -> str:
    from app.core.config import settings
    return (settings.GEMINI_API_KEY or "").strip()


def _openai_api_key() -> str:
    from app.core.config import settings
    return (settings.OPENAI_API_KEY or "").strip()


def _gemini_configured() -> bool:
    key = _gemini_api_key()
    return bool(key) and key.upper() not in {k.upper() for k in _GEMINI_PLACEHOLDER_KEYS}


def _get_client() -> genai.Client:
    """Create a Gemini client using GEMINI_API_KEY."""
    api_key = _gemini_api_key()
    if not api_key or not _gemini_configured():
        raise ValueError(
            "GEMINI_API_KEY not set or is a placeholder. Add a valid key to .env."
        )

    return genai.Client(api_key=api_key)


def openai_json_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    schema: Type[_SchemaT],
    temperature: float = 0.0,
    max_completion_tokens: int = 250,
) -> dict:
    """
    Call OpenAI chat completions and parse a JSON object matching ``schema``.

    Used as the voice-agent fallback when Gemini is unavailable or errors.
    """
    from openai import OpenAI

    api_key = _openai_api_key()
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set. Add it to .env or settings.")

    schema_hint = json.dumps(schema.model_json_schema())
    system = (
        f"{system_prompt}\n\n"
        "Respond with a single JSON object only (no markdown) matching this schema:\n"
        f"{schema_hint}"
    )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=_get_openai_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)


# ── Valid specialties ─────────────────────────────────────────────────────────

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


def _keyword_hint(problem: str) -> Optional[str]:
    """Fast keyword-based specialty hint as a fallback/boost signal."""
    problem_lower = problem.lower()
    for specialty, keywords in SPECIALTY_KEYWORDS.items():
        if any(kw in problem_lower for kw in keywords):
            return specialty
    return None


# ── Pydantic response schemas ─────────────────────────────────────────────────
# Gemini's structured output guarantees conformance to these schemas.

class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class NameExtractionResult(BaseModel):
    """Result of extracting a patient name from speech transcript."""
    found: bool = Field(description="True if a valid patient name was found in the transcript")
    name: str = Field(default="", description="The extracted patient name, properly capitalised")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.low, description="Confidence level")
    reason: str = Field(default="", description="One short sentence explaining the extraction result")


class SeverityLevel(str, Enum):
    urgent = "urgent"
    routine = "routine"
    unclear = "unclear"


class ProblemExtractionResult(BaseModel):
    """Result of extracting a medical problem from speech transcript."""
    found: bool = Field(description="True if a medical problem/symptom was described")
    problem: str = Field(default="", description="Cleaned medical problem description in the patient's spoken language")
    severity: SeverityLevel = Field(default=SeverityLevel.unclear, description="Urgency assessment: urgent (emergency symptoms), routine (standard), or unclear")
    keywords: list[str] = Field(default_factory=list, description="Up to 3 medical keywords in English for specialty matching")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.low, description="Confidence level")
    reason: str = Field(default="", description="One short sentence explaining the extraction result")


class SpecialtyDetectionResult(BaseModel):
    """Result of mapping a medical problem to a specialty."""
    specialty: str = Field(description="One of the valid medical specialties")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.low, description="Confidence level")
    reasoning: str = Field(default="", description="One short sentence explaining the specialty choice")


# ── 1. Name extraction ────────────────────────────────────────────────────────
# Multi-stage pipeline lives in app.agent.name_extraction; this is the public facade.


def extract_patient_name(transcript: str, twilio_confidence: float = -1.0) -> dict:
    """
    Extract the patient's name from a speech transcript via the multi-stage pipeline.

    Stages: preprocess → regex rules → Gemini → postprocess → validate → fallback.

    Returns dict with keys: found, name, confidence, reason
    """
    from app.agent.name_extraction.pipeline import run

    return run(transcript, twilio_confidence=twilio_confidence)


# ── 2. Problem extraction ─────────────────────────────────────────────────────

PROBLEM_SYSTEM_PROMPT = """You are a medical receptionist assistant for NexaCare, an Indian hospital.
The patient was asked "Please describe your health problem or symptoms."

The patient may have spoken in English, Hindi, or Marathi. The transcript may
contain Devanagari script (Hindi/Marathi), Latin script (English or
transliterated Hindi/Marathi), or a mix.

Your job: extract, normalise, and assess the STRICT medical problem from the transcript.

Rules:
- STRICTLY EXTRACT ONLY THE SPECIFIC SYMPTOMS OR PROBLEM. DO NOT include filler words like "I am having", "I feel", "Mujhe", "Mala", etc.
- Output just the core medical issue (e.g., "chest pain", "headache", "सिरदर्द", "पोटात दुखणे").
- CRITICAL: Write the cleaned "problem" in the SAME language the patient spoke.
  Hindi stays in Hindi/Devanagari, Marathi stays in Marathi/Devanagari,
  English stays in English. This text will be read back to the patient
  by text-to-speech, so do NOT translate it.
- Assess severity: "urgent" for chest pain, difficulty breathing, severe bleeding,
  loss of consciousness, etc. "routine" for standard symptoms. "unclear" if unsure.
- Extract up to 3 medical keywords in ENGLISH (regardless of input language)
  for specialty matching. Examples: ["chest pain", "shortness of breath", "sweating"]
- If the patient described a clear problem, set found to true.
- If the transcript is too unclear, too short, or not health-related, set found to false.
- Be generous — if there's ANY health information, extract it regardless of language."""


def extract_problem(transcript: str, twilio_confidence: float = -1.0) -> dict:
    """
    Extract and normalise the patient's problem from transcript.

    Tries Gemini first, then OpenAI, then raw-transcript fallback.

    Returns dict with keys: found, problem, severity, keywords, confidence, reason
    """
    if not transcript or not transcript.strip():
        return {"found": False, "problem": "", "confidence": "low", "reason": "Empty transcript."}

    logger.info(
        f"Problem extraction attempt | transcript={transcript!r} | "
        f"twilio_confidence={twilio_confidence}"
    )

    user_content = f'Speech transcript: "{transcript.strip()}"'
    gemini_error: Exception | None = None

    if _gemini_configured():
        try:
            client = _get_client()
            model = _get_model()

            response = client.models.generate_content(
                model=model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=PROBLEM_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_output_tokens=250,
                    response_mime_type="application/json",
                    response_schema=ProblemExtractionResult,
                ),
            )

            result = json.loads(response.text)
            return _normalise_problem_result(result)

        except Exception as e:
            gemini_error = e
            logger.warning(f"Problem extraction Gemini failed: {e} — trying OpenAI")
    else:
        logger.info("Problem extraction: Gemini not configured — trying OpenAI")

    try:
        result = openai_json_completion(
            system_prompt=PROBLEM_SYSTEM_PROMPT,
            user_prompt=user_content,
            schema=ProblemExtractionResult,
            temperature=0.0,
            max_completion_tokens=250,
        )
        logger.info("Problem extraction succeeded via OpenAI fallback")
        return _normalise_problem_result(result)

    except Exception as e:
        err = gemini_error or e
        logger.warning(
            f"Problem extraction OpenAI failed: {e} — using raw transcript as fallback"
        )
        problem = transcript.strip()
        if len(problem.replace(" ", "")) >= 4:
            return {
                "found": True, "problem": problem, "confidence": "low",
                "severity": "unclear", "keywords": [],
                "reason": "LLM error — raw transcript used.",
            }
        return {
            "found": False, "problem": "", "confidence": "low",
            "reason": f"LLM error: {str(err)[:60]}",
        }


def _normalise_problem_result(result: dict) -> dict:
    if not isinstance(result.get("found"), bool):
        result["found"] = bool(result.get("problem", "").strip())
    if not result.get("problem", "").strip():
        result["found"] = False
        result["problem"] = ""

    logger.info(
        f"Problem extraction: found={result['found']} "
        f"severity={result.get('severity')} keywords={result.get('keywords')} "
        f"conf={result.get('confidence')} | {result.get('reason')}"
    )
    return result


# ── 3. Specialty detection ────────────────────────────────────────────────────

_SPECIALTY_LIST = "\n".join(f"- {s}" for s in VALID_SPECIALTIES)

SPECIALTY_SYSTEM_PROMPT = f"""You are a medical triage assistant for NexaCare hospital.
Analyse the patient's problem and return the most appropriate medical specialty.

The problem description may be in English, Hindi, or Marathi
(Devanagari or Latin script). Understand it regardless of language.

Available specialties:
{_SPECIALTY_LIST}

Rules:
- Select the SINGLE most appropriate specialty from the list above.
- If unsure or the problem is vague, use "General Medicine".
- Be conservative: prefer common conditions over rare ones.
- If multiple specialties could apply, choose the primary/most urgent one.
- Consider the English keywords (if provided) as additional signal."""


def detect_specialty(problem_description: str, keywords: list[str] | None = None) -> dict:
    """
    Detect medical specialty from patient's cleaned problem description.

    Tries Gemini first, then OpenAI, then keyword hint.

    Args:
        problem_description: The cleaned problem text (in patient's language)
        keywords: Optional list of English medical keywords from problem extraction

    Returns dict with keys: specialty, confidence, reasoning
    """
    hint = _keyword_hint(problem_description)

    # Also check keywords for hints
    if not hint and keywords:
        for kw in keywords:
            hint = _keyword_hint(kw)
            if hint:
                break

    user_prompt = f'Patient problem: "{problem_description}"'
    if keywords:
        user_prompt += f'\nMedical keywords: {", ".join(keywords)}'
    if hint:
        user_prompt += f'\nKeyword analysis suggests: "{hint}". Confirm or override based on full context.'

    if _gemini_configured():
        try:
            client = _get_client()
            model = _get_model()

            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SPECIALTY_SYSTEM_PROMPT,
                    temperature=0.1,
                    max_output_tokens=150,
                    response_mime_type="application/json",
                    response_schema=SpecialtyDetectionResult,
                ),
            )

            result = json.loads(response.text)
            return _normalise_specialty_result(result, hint)

        except Exception as e:
            logger.warning(f"Specialty detection Gemini failed: {e} — trying OpenAI")
    else:
        logger.info("Specialty detection: Gemini not configured — trying OpenAI")

    try:
        result = openai_json_completion(
            system_prompt=SPECIALTY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=SpecialtyDetectionResult,
            temperature=0.1,
            max_completion_tokens=150,
        )
        logger.info("Specialty detection succeeded via OpenAI fallback")
        return _normalise_specialty_result(result, hint)

    except Exception as e:
        logger.warning(f"Specialty detection OpenAI failed: {e} — using keyword hint")
        return {
            "specialty": hint or "General Medicine",
            "confidence": "low",
            "reasoning": "AI analysis unavailable — keyword fallback used.",
        }


def _normalise_specialty_result(result: dict, hint: Optional[str]) -> dict:
    if result.get("specialty") not in VALID_SPECIALTIES:
        result["specialty"] = hint or "General Medicine"
        result["confidence"] = "low"
        result["reasoning"] = "Specialty not recognised — routing to General Medicine."

    logger.info(
        f"Specialty: {result['specialty']} ({result['confidence']}) | {result['reasoning']}"
    )
    return result