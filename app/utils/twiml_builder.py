from xml.sax.saxutils import escape


def twiml_response(*elements: str) -> str:
    body = "".join(elements)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def say(
    text: str,
    language: str = "en-US",
    voice: str | None = None,
    voice_gender: str | None = None,
) -> str:
    """Generate <Say>. Prefer explicit voice profile; else map gender to provider voice."""
    voice_name = voice
    if not voice_name and voice_gender:
        gender = voice_gender.lower()
        if language.startswith("hi"):
            voice_name = "Polly.Aditi" if gender == "female" else "Polly.Matthew"
        elif language.startswith("mr"):
            voice_name = (
                "Google.mr-IN-Standard-A" if gender == "female" else "Google.mr-IN-Standard-B"
            )
        else:
            voice_name = (
                "Google.en-IN-Standard-A" if gender == "female" else "Google.en-IN-Standard-B"
            )
    voice_attr = f' voice="{escape(voice_name)}"' if voice_name else ""
    return f'<Say language="{escape(language)}"{voice_attr}>{escape(text)}</Say>'


def hangup() -> str:
    return "<Hangup/>"


def gather(
    action_url: str,
    prompt: str,
    num_digits: int = 1,
    language: str = "en-US",
    voice: str | None = None,
    voice_gender: str | None = None,
    timeout_redirect_url: str | None = None,
) -> str:
    if timeout_redirect_url:
        timeout_action = (
            f"{say('I did not receive your selection. Continuing with speech.', language, voice, voice_gender)}"
            f'<Redirect method="POST">{escape(timeout_redirect_url)}</Redirect>'
        )
    else:
        timeout_action = (
            f"{say('We did not receive your input. Goodbye.', language, voice, voice_gender)}"
        )
    return (
        f'<Gather numDigits="{num_digits}" action="{escape(action_url)}" method="POST" timeout="10">'
        f"{say(prompt, language, voice, voice_gender)}"
        "</Gather>"
        f"{timeout_action}"
    )


def gather_speech(
    action_url: str,
    prompt: str,
    language: str = "en-IN",
    speech_timeout: str = "auto",
    hints: str | None = None,
    timeout: int = 8,
    voice: str | None = None,
    voice_gender: str | None = None,
) -> str:
    hints_attr = f' hints="{escape(hints)}"' if hints else ""
    return (
        f'<Gather input="speech" action="{escape(action_url)}" method="POST" '
        f'language="{escape(language)}" speechTimeout="{speech_timeout}" '
        f'timeout="{timeout}"{hints_attr}>'
        f"{say(prompt, language, voice, voice_gender)}"
        "</Gather>"
        f"{say('I could not hear properly. Could you please repeat?', language, voice, voice_gender)}"
        f'<Redirect method="POST">{escape(action_url)}</Redirect>'
    )


def gather_speech_or_dtmf(
    action_url: str,
    prompt: str,
    language: str = "en-IN",
    num_digits: int = 1,
    speech_timeout: str = "auto",
    hints: str | None = None,
    voice: str | None = None,
    voice_gender: str | None = None,
) -> str:
    hints_attr = f' hints="{escape(hints)}"' if hints else ""
    return (
        f'<Gather input="speech dtmf" numDigits="{num_digits}" action="{escape(action_url)}" '
        f'method="POST" language="{escape(language)}" speechTimeout="{speech_timeout}" '
        f'timeout="10"{hints_attr}>'
        f"{say(prompt, language, voice, voice_gender)}"
        "</Gather>"
        f"{say('I could not hear properly. Could you please repeat?', language, voice, voice_gender)}"
        f'<Redirect method="POST">{escape(action_url)}</Redirect>'
    )


def redirect(url: str) -> str:
    return f'<Redirect method="POST">{escape(url)}</Redirect>'


def dial(number: str, action_url: str | None = None, timeout: int = 30) -> str:
    action_attr = f' action="{escape(action_url)}" method="POST"' if action_url else ""
    return (
        f'<Dial timeout="{timeout}"{action_attr}>'
        f"<Number>{escape(number)}</Number>"
        "</Dial>"
    )


def enqueue(wait_url: str | None = None) -> str:
    if wait_url:
        return f'<Enqueue waitUrl="{escape(wait_url)}">reception</Enqueue>'
    return "<Enqueue>reception</Enqueue>"


def twilio_say_language(lang_code: str) -> str:
    mapping = {
        "en": "en-IN",
        "hi": "hi-IN",
        "mr": "mr-IN",
    }
    return mapping.get(lang_code, "en-IN")
