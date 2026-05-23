from typing import List

from app.utils.ai_llm import llm_service


class SymptomAnalyzer:
    SYMPTOM_MAP = {
        "fever": ("viral_infection", "general_physician", "medium"),
        "cough": ("respiratory_infection", "pulmonologist", "medium"),
        "chest pain": ("cardiac_concern", "cardiologist", "high"),
        "headache": ("tension_headache", "neurologist", "low"),
        "nausea": ("gastrointestinal", "gastroenterologist", "medium"),
    }

    async def analyze(self, symptoms: List[str]) -> dict:
        possible = []
        urgency = "low"
        specialist = "general_physician"

        for symptom in symptoms:
            key = symptom.lower().strip()
            for pattern, (condition, spec, urg) in self.SYMPTOM_MAP.items():
                if pattern in key:
                    possible.append(condition)
                    specialist = spec
                    if urg == "high":
                        urgency = "high"
                    elif urg == "medium" and urgency != "high":
                        urgency = "medium"

        if len(symptoms) >= 4 and urgency == "low":
            urgency = "medium"

        return {
            "symptoms": symptoms,
            "possible_conditions": possible or ["requires_clinical_evaluation"],
            "recommended_specialist": specialist,
            "urgency": urgency,
            "sentiment": await llm_service.analyze_sentiment(" ".join(symptoms)),
        }
