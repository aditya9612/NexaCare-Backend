from celery import Celery

from app.core.config import settings

broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
result_backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery(
    "nesacare_hms",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.tasks.voice_tasks",
        "app.tasks.whatsapp_tasks",
        "app.tasks.analytics_tasks",
        "app.tasks.chat_tasks",
        "app.tasks.reminder_tasks",
        "app.tasks.lab_tasks",
    ],
)

# Webhook paths (.delay() on transfer/callback) must never block on broker retries.
# Tickets are persisted before enqueue; beat picks up missed enqueues when Redis is down.
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=False,
    task_publish_retry=False,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_connect_timeout": 1,
        "socket_timeout": 1,
        "max_retries": 0,
    },
    result_backend_transport_options={
        "socket_connect_timeout": 1,
        "socket_timeout": 1,
        "max_retries": 0,
    },
    beat_schedule={
        "process-pending-voice-calls": {
            "task": "app.tasks.voice_tasks.process_pending_calls",
            "schedule": 300.0,
        },
        "refresh-analytics-cache": {
            "task": "app.tasks.analytics_tasks.refresh_dashboard_cache",
            "schedule": 600.0,
        },
        "schedule-voice-reminders": {
            "task": "app.tasks.reminder_tasks.schedule_appointment_voice_reminders",
            "schedule": 3600.0,
        },
        "process-reception-callback-tickets": {
            "task": "app.tasks.voice_tasks.process_reception_callback_tickets",
            "schedule": 600.0,
        },
        "check-pending-lab-tests": {
            "task": "app.tasks.lab_tasks.check_pending_lab_tests",
            "schedule": 900.0,
        },
        "process-doctor-appointment-reminders": {
            "task": "app.tasks.reminder_tasks.process_doctor_appointment_reminders",
            "schedule": 300.0,
        },
        "process-medication-reminders": {
            "task": "app.tasks.reminder_tasks.process_medication_reminders",
            "schedule": 60.0,
        },
    },
)
