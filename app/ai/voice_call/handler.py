from typing import Any, Dict


class VoiceCallHandler:
    DTMF_ACTIONS = {
        "1": "confirm_appointment",
        "2": "cancel_appointment",
        "3": "reschedule_appointment",
        "0": "repeat_menu",
    }

    MENU_BY_LANG = {
        "en": "Press 1 to confirm, 2 to cancel, 3 to reschedule, 0 to repeat.",
        "hi": "पुष्टि के लिए 1 दबाएं, रद्द करने के लिए 2, पुनर्निर्धारण के लिए 3, दोबारा सुनने के लिए 0।",
        "mr": "निश्चित करण्यासाठी 1 दाबा, रद्द करण्यासाठी 2, वेळ बदलण्यासाठी 3, पुन्हा ऐकण्यासाठी 0.",
    }

    NO_INPUT_BY_LANG = {
        "en": "We did not receive your input. Goodbye.",
        "hi": "हमें आपका इनपुट नहीं मिला। नमस्कार।",
        "mr": "आम्हाला आपला निवड मिळाला नाही. नमस्कार.",
    }

    async def process_audio(self, audio_path: str) -> Dict[str, Any]:
        return {
            "transcript": "",
            "intent": "appointment_reminder",
            "audio_path": audio_path,
            "menu": self.MENU_BY_LANG["en"],
        }

    def menu_for_language(self, language: str) -> str:
        return self.MENU_BY_LANG.get(language, self.MENU_BY_LANG["en"])

    def no_input_for_language(self, language: str) -> str:
        return self.NO_INPUT_BY_LANG.get(language, self.NO_INPUT_BY_LANG["en"])

    def parse_dtmf(self, digits: str) -> str:
        return self.DTMF_ACTIONS.get(digits.strip(), "unknown")

    async def generate_voice_prompt(self, language: str = "en") -> str:
        prompts = {
            "en": "Hello, this is NesaCare calling about your upcoming appointment.",
            "hi": "नमस्ते, यह नेसाकेयर आपकी आगामी अपॉइंटमेंट के बारे में कॉल कर रहा है।",
            "mr": "नमस्कार, हे नेसाकेयर आपल्या आगामी भेटीबद्दल कॉल करत आहे.",
        }
        return prompts.get(language, prompts["en"])

    def dtmf_response(self, action: str, language: str) -> str:
        responses = {
            "confirm": {
                "en": "Thank you. Your appointment is confirmed. Goodbye.",
                "hi": "धन्यवाद। आपकी अपॉइंटमेंट की पुष्टि हो गई है। नमस्कार।",
                "mr": "धन्यवाद. आपली भेट निश्चित झाली. नमस्कार.",
            },
            "cancel": {
                "en": "Your appointment has been cancelled. Goodbye.",
                "hi": "आपकी अपॉइंटमेंट रद्द कर दी गई है। नमस्कार।",
                "mr": "आपली भेट रद्द झाली. नमस्कार.",
            },
            "reschedule": {
                "en": "We have noted your reschedule request. Our team will contact you shortly. Goodbye.",
                "hi": "हमने आपका पुनर्निर्धारण अनुरोध नोट कर लिया है। हमारी टीम शीघ्र संपर्क करेगी। नमस्कार।",
                "mr": "आम्ही तुमची वेळ बदलण्याची विनंती नोंदवली आहे. आमची टीम लवकरच संपर्क करेल. नमस्कार.",
            },
            "invalid": {
                "en": "Invalid option. Goodbye.",
                "hi": "अमान्य विकल्प। नमस्कार।",
                "mr": "अवैध निवड. नमस्कार.",
            },
        }
        lang_map = responses.get(action, responses["invalid"])
        return lang_map.get(language, lang_map["en"])
