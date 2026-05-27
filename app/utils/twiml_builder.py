from xml.sax.saxutils import escape


def twiml_response(*elements: str) -> str:
    body = "".join(elements)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def say(text: str, language: str = "en-US") -> str:
    return f'<Say language="{language}">{escape(text)}</Say>'


def hangup() -> str:
    return "<Hangup/>"


def gather(action_url: str, prompt: str, num_digits: int = 1, language: str = "en-US") -> str:
    return (
        f'<Gather numDigits="{num_digits}" action="{escape(action_url)}" method="POST" timeout="10">'
        f"{say(prompt, language)}"
        "</Gather>"
        f"{say('We did not receive your input. Goodbye.', language)}"
    )


def gather_speech(
    action_url: str,
    prompt: str,
    language: str = "en-IN",
    speech_timeout: str = "auto",
    hints: str | None = None,
    timeout: int = 8,
) -> str:
    hints_attr = f' hints="{escape(hints)}"' if hints else ""
    return (
        f'<Gather input="speech" action="{escape(action_url)}" method="POST" '
        f'language="{escape(language)}" speechTimeout="{speech_timeout}" '
        f'timeout="{timeout}"{hints_attr}>'
        f"{say(prompt, language)}"
        "</Gather>"
        f"{say('I could not hear properly. Could you please repeat?', language)}"
        f'<Redirect method="POST">{escape(action_url)}</Redirect>'
    )


def gather_speech_or_dtmf(
    action_url: str,
    prompt: str,
    language: str = "en-IN",
    num_digits: int = 1,
    speech_timeout: str = "auto",
    hints: str | None = None,
) -> str:
    """Speech-first gather; Twilio also accepts DTMF on the same Gather when input includes speech."""
    hints_attr = f' hints="{escape(hints)}"' if hints else ""
    return (
        f'<Gather input="speech dtmf" numDigits="{num_digits}" action="{escape(action_url)}" '
        f'method="POST" language="{escape(language)}" speechTimeout="{speech_timeout}" '
        f'timeout="10"{hints_attr}>'
        f"{say(prompt, language)}"
        "</Gather>"
        f"{say('I could not hear properly. Could you please repeat?', language)}"
        f'<Redirect method="POST">{escape(action_url)}</Redirect>'
    )


def redirect(url: str) -> str:
    return f'<Redirect method="POST">{escape(url)}</Redirect>'


def twilio_say_language(lang_code: str) -> str:
    """Map short language codes to Twilio Say/Gather language codes."""
    mapping = {
        "en": "en-IN",
        "hi": "hi-IN",
        "mr": "mr-IN",
    }
    return mapping.get(lang_code, "en-IN")
