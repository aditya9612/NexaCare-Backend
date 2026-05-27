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
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
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
    },
)
