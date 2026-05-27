# Nexa-Care HMS Backend

Hospital Management System API built with FastAPI, SQLAlchemy, and MySQL.

## Quick start

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # edit OPENAI_API_KEY, TWILIO_*, REDIS_URL
python run.py
```

API docs: http://localhost:8000/docs

## AI features

### 1. AI Appointment Assistant (in-chat)

Multi-turn booking via `POST /api/v1/ai/chat/send-message` when intent is `book_appointment`.

- Progress: `GET /api/v1/ai/chat/booking-state/{session_id}`
- Manual override: `POST /api/v1/ai/chat/book-appointment`

Example flow:

1. `POST /api/v1/ai/chat/start-session` with `{ "patient_id": 1, "language": "en" }`
2. `POST /api/v1/ai/chat/send-message` — "I have fever and need an appointment tomorrow at 10am"
3. Reply `YES` to confirm when prompted

### 2. AI Patient Chatbot

- REST: `/api/v1/ai/chat/*`
- WebSocket: `ws://localhost:8000/ws/chat/{session_id}?token=<JWT>`
- Intents: FAQ, symptom check, booking, escalation
- Rate limit: `CHAT_RATE_LIMIT_PER_MINUTE` (default 30)

### 3. AI Voice Appointment Assistant (Twilio speech)

Multilingual (English/Hindi/Marathi) inbound phone assistant for booking, rescheduling, cancellation, doctor availability, and hospital info.

**Twilio webhooks (no auth):**

- `POST /api/v1/voice-assistant/twiml/inbound` — incoming calls
- `POST /api/v1/voice-assistant/twiml/start` — call start / outbound assistant
- `POST /api/v1/voice-assistant/twiml/turn` — speech/DTMF turn handler

Point your Twilio phone number voice URL to `{PUBLIC_BASE_URL}/api/v1/voice-assistant/twiml/inbound`.

For outbound assistant calls, schedule with `call_type: "appointment_assistant"`.

### 4. AI Voice Call Reminder (Twilio IVR)

Outbound calls with DTMF menu (1=confirm, 2=cancel, 3=reschedule).

**Twilio setup (local dev):**

```bash
ngrok http 8000
# Set PUBLIC_BASE_URL=https://<ngrok-id>.ngrok.io in .env
```

Public webhooks (no auth):

- `POST /api/v1/voice-reminder/twiml/{call_id}`
- `POST /api/v1/voice-reminder/twiml/{call_id}/gather`
- `POST /api/v1/voice-reminder/status-callback`

Staff APIs: `POST /voice-reminder/schedule`, `GET /voice-reminder/call-analytics`

**Auto reminders:** Celery beat runs `schedule_appointment_voice_reminders` hourly for tomorrow's appointments.

```bash
celery -A app.celery_app worker --loglevel=info
celery -A app.celery_app beat --loglevel=info
```

## Environment variables

See [.env.example](.env.example) for:

- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
- `PUBLIC_BASE_URL` (required for live voice calls)
- `REDIS_URL`, `CELERY_BROKER_URL`

## Docker

```bash
docker compose up --build
```

## Migrations

```bash
alembic upgrade head
```

## Tests

```bash
pytest app/tests -v
```
