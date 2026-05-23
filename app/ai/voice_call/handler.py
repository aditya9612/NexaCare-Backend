from typing import Any, Dict


class VoiceCallHandler:
    DTMF_ACTIONS = {
        "1": "confirm_appointment",
        "2": "cancel_appointment",
        "3": "reschedule_appointment",
        "0": "repeat_menu",
    }

    async def process_audio(self, audio_path: str) -> Dict[str, Any]:
        return {
            "transcript": "",
            "intent": "appointment_reminder",
            "audio_path": audio_path,
            "menu": "Press 1 to confirm, 2 to cancel, 3 to reschedule",
        }

    def parse_dtmf(self, digits: str) -> str:
        return self.DTMF_ACTIONS.get(digits.strip(), "unknown")

    async def generate_voice_prompt(self, language: str = "en") -> str:
        prompts = {
            "en": "Hello, this is NesaCare calling about your upcoming appointment.",
            "hi": "नमस्ते, यह नेसाकेयर आपकी आगामी अपॉइंटमेंट के बारे में कॉल कर रहा है।",
            "es": "Hola, le llama NesaCare sobre su próxima cita.",
        }
        return prompts.get(language, prompts["en"])
