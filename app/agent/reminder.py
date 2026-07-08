"""
app/agent/reminder.py
---------------------
Appointment reminder system for NexaCare HMS.

Flow:
  1. APScheduler runs process_reminders() every hour
  2. Finds appointments scheduled for tomorrow with reminder_sent=False
  3. Makes an outbound Twilio call to the patient
  4. If call is not answered (no-answer/busy/failed) → sends SMS instead
  5. Marks reminder_sent=True in DB
"""

import logging
import os
import re
import urllib.parse
from datetime import date, datetime, timedelta

logger = logging.getLogger("nexacare.agent.reminder")

# ── Localized reminder strings ────────────────────────────────────────────────

CALL_REMINDER = {
    "en": (
        "Hello! This is an automated reminder from NexaCare Hospital. "
        "You have an appointment tomorrow with Doctor {doctor} at {time}. "
        "Your appointment number is {appt_no}. "
        "Please arrive 10 minutes early. Thank you. Goodbye."
    ),
    "hi": (
        "नमस्ते! यह NexaCare हॉस्पिटल की तरफ से स्वचालित याद दिलाने के लिए कॉल है। "
        "कल डॉक्टर {doctor} के साथ {time} बजे आपकी अपॉइंटमेंट है। "
        "अपॉइंटमेंट नंबर {appt_no} है। "
        "कृपया 10 मिनट पहले आएं। धन्यवाद।"
    ),
    "mr": (
        "नमस्कार! हे NexaCare हॉस्पिटलकडून स्वयंचलित स्मरणपत्र आहे. "
        "उद्या डॉक्टर {doctor} यांच्याशी {time} वाजता तुमची अपॉइंटमेंट आहे. "
        "अपॉइंटमेंट नंबर {appt_no} आहे. "
        "कृपया 10 मिनिटे आधी या. धन्यवाद."
    ),
}

SMS_REMINDER = {
    "en": (
        "NexaCare Reminder: You have an appointment tomorrow with "
        "Dr. {doctor} at {time}. Appt No: {appt_no}. "
        "Please arrive 10 mins early."
    ),
    "hi": (
        "NexaCare याद दिलाएं: कल डॉ. {doctor} के साथ {time} बजे "
        "अपॉइंटमेंट है। नं: {appt_no}। 10 मिनट पहले पहुंचें।"
    ),
    "mr": (
        "NexaCare स्मरणपत्र: उद्या डॉ. {doctor} यांच्याशी {time} वाजता "
        "अपॉइंटमेंट आहे. नं: {appt_no}. 10 मिनिटे आधी या."
    ),
}

TWILIO_LANG_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
    "mr": "mr-IN",
}

VOICE_BY_LANG = {
    "mr-IN": "Google.mr-IN-Chirp3-HD-Aoede",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_from_notes(notes: str) -> dict:
    """Extract phone number and language from appointment notes field."""
    result = {"phone": None, "lang": "en"}
    if not notes:
        return result
    phone_match = re.search(r"Phone:\s*(\+\d+)", notes)
    if phone_match:
        result["phone"] = phone_match.group(1)
    lang_match = re.search(r"Lang:\s*(\w+)", notes)
    if lang_match:
        result["lang"] = lang_match.group(1)
    return result


def _format_time(time_str: str) -> str:
    try:
        t = datetime.strptime(str(time_str), "%H:%M:%S")
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(time_str)


def build_reminder_twiml(lang: str, doctor: str, time_str: str, appt_no: str) -> str:
    """Build TwiML for the outbound reminder call."""
    from xml.sax.saxutils import escape
    twilio_lang = TWILIO_LANG_MAP.get(lang, "en-IN")
    voice = VOICE_BY_LANG.get(twilio_lang, "")
    voice_attr = f' voice="{escape(voice)}"' if voice else ""
    text = CALL_REMINDER.get(lang, CALL_REMINDER["en"]).format(
        doctor=doctor, time=time_str, appt_no=appt_no
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say language="{escape(twilio_lang)}"{voice_attr}>{escape(text)}</Say>'
        "<Hangup/>"
        "</Response>"
    )


# ── SMS fallback ──────────────────────────────────────────────────────────────

async def send_reminder_sms(
    phone: str, lang: str, doctor: str, time_str: str, appt_no: str
) -> bool:
    """Send SMS reminder — used as fallback when call is not answered."""
    try:
        from twilio.rest import Client
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token  = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_PHONE_NUMBER")

        if not all([account_sid, auth_token, from_number, phone]):
            logger.warning("[Reminder] SMS skipped: missing Twilio credentials")
            return False

        template = SMS_REMINDER.get(lang, SMS_REMINDER["en"])
        body = template.format(doctor=doctor, time=time_str, appt_no=appt_no)

        client = Client(account_sid, auth_token)
        msg = client.messages.create(body=body, from_=from_number, to=phone)
        logger.info(f"[Reminder] ✓ SMS sent to {phone} | SID={msg.sid}")
        return True

    except Exception as e:
        logger.warning(f"[Reminder] SMS failed: {e}")
        return False


# ── Outbound call ─────────────────────────────────────────────────────────────

async def make_reminder_call(
    phone: str,
    lang: str,
    doctor: str,
    time_str: str,
    appt_no: str,
    base_url: str,
) -> bool:
    """
    Initiate outbound Twilio call with reminder TwiML.
    Twilio will POST to /reminder-status if call is not answered.
    """
    try:
        from twilio.rest import Client
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token  = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_PHONE_NUMBER")

        if not all([account_sid, auth_token, from_number, phone]):
            logger.warning("[Reminder] Call skipped: missing Twilio credentials")
            return False

        params = urllib.parse.urlencode({
            "doctor":  doctor,
            "time":    time_str,
            "lang":    lang,
            "appt_no": appt_no,
            "phone":   phone,
        })
        twiml_url  = f"{base_url}/agent/v1/voice/reminder-twiml?{params}"
        status_url = f"{base_url}/agent/v1/voice/reminder-status?{params}"

        client = Client(account_sid, auth_token)
        call = client.calls.create(
            to=phone,
            from_=from_number,
            url=twiml_url,
            status_callback=status_url,
            status_callback_method="POST",
            status_callback_event=["no-answer", "busy", "failed", "completed"],
            timeout=30,
        )
        logger.info(f"[Reminder] ✓ Call initiated to {phone} | SID={call.sid}")
        return True

    except Exception as e:
        logger.warning(f"[Reminder] Call failed: {e}")
        return False


# ── Core scheduler job ────────────────────────────────────────────────────────

async def process_reminders(db_factory) -> None:
    """
    Find all appointments scheduled for tomorrow that haven't been reminded yet,
    then call each patient. Falls back to SMS if call initiation fails.
    """
    from sqlalchemy import select, and_
    from app.models.appointment_model import Appointment
    from app.models.doctor_model import Doctor

    base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    tomorrow = date.today() + timedelta(days=1)

    logger.info(f"[Reminder] Scanning appointments for {tomorrow} ...")

    try:
        async with db_factory() as db:
            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.appointment_date == tomorrow,
                        Appointment.reminder_sent == False,
                        Appointment.appointment_status == "scheduled",
                    )
                )
            )
            appointments = result.scalars().all()
            logger.info(f"[Reminder] {len(appointments)} appointment(s) need reminders")

            for appt in appointments:
                try:
                    # Get doctor name
                    doc_result = await db.execute(
                        select(Doctor).where(Doctor.id == appt.doctor_id)
                    )
                    doctor = doc_result.scalar_one_or_none()
                    doctor_name = (
                        f"{doctor.first_name} {doctor.last_name}"
                        if doctor else "the doctor"
                    )

                    # Extract patient contact from notes
                    info     = _extract_from_notes(appt.notes or "")
                    phone    = info["phone"]
                    lang     = info["lang"]
                    time_str = _format_time(str(appt.appointment_time))

                    if not phone:
                        logger.warning(
                            f"[Reminder] No phone found for {appt.appointment_number} — skipping"
                        )
                        continue

                    logger.info(
                        f"[Reminder] Processing {appt.appointment_number} | "
                        f"phone={phone} | lang={lang} | doctor={doctor_name} | time={time_str}"
                    )

                    # Try call first — SMS is the fallback (handled by /reminder-status)
                    call_ok = await make_reminder_call(
                        phone=phone,
                        lang=lang,
                        doctor=doctor_name,
                        time_str=time_str,
                        appt_no=appt.appointment_number,
                        base_url=base_url,
                    )

                    if not call_ok:
                        # Call initiation itself failed — send SMS immediately
                        logger.warning(
                            f"[Reminder] Call initiation failed for {appt.appointment_number} "
                            "— falling back to SMS"
                        )
                        await send_reminder_sms(
                            phone=phone,
                            lang=lang,
                            doctor=doctor_name,
                            time_str=time_str,
                            appt_no=appt.appointment_number,
                        )

                    # Mark reminded regardless of outcome
                    appt.reminder_sent = True
                    await db.commit()
                    logger.info(f"[Reminder] ✓ {appt.appointment_number} marked as reminded")

                except Exception as e:
                    logger.error(f"[Reminder] Error on {appt.appointment_number}: {e}")
                    await db.rollback()

    except Exception as e:
        logger.error(f"[Reminder] DB error: {e}")


# ── Scheduler startup ─────────────────────────────────────────────────────────

def start_reminder_scheduler(db_factory):
    """
    Start APScheduler to run process_reminders() every hour.
    Call this once from main.py lifespan after init_db().
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        process_reminders,
        trigger="interval",
        hours=1,
        args=[db_factory],
        id="appointment_reminders",
        name="NexaCare appointment reminders",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[Reminder] ✓ Scheduler started — reminders will run every hour (IST)")
    return scheduler