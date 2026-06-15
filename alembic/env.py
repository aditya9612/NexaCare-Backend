from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import Base

import app.models.user_model  # noqa: F401
import app.models.role_model  # noqa: F401
import app.models.permission_model  # noqa: F401
import app.models.refresh_token_model  # noqa: F401
import app.models.patient_model  # noqa: F401
import app.models.doctor_model  # noqa: F401
import app.models.department_model  # noqa: F401
import app.models.appointment_model  # noqa: F401
import app.models.pharmacy_model  # noqa: F401
import app.models.billing_model  # noqa: F401
import app.models.inventory_model  # noqa: F401
import app.models.lab_model  # noqa: F401
import app.models.nurse_model  # noqa: F401
import app.models.audit_log_model  # noqa: F401
import app.models.bed_allocation_model  # noqa: F401
import app.models.hospital_model  # noqa: F401
import app.models.subscription_model  # noqa: F401
import app.models.ai_config_model  # noqa: F401
import app.models.security_model  # noqa: F401
import app.models.staff_model  # noqa: F401

config = context.config
database_url = settings.DATABASE_URL_SYNC.replace("%", "%%")
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
