import logging
import sys

from app.core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

_sql_log_level = logging.INFO if settings.SQLALCHEMY_ECHO else logging.WARNING
for _sql_logger in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects"):
    logging.getLogger(_sql_logger).setLevel(_sql_log_level)

logger = logging.getLogger("hms")
