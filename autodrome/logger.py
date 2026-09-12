import logging
import os
import re
from logging.handlers import RotatingFileHandler
from typing import Optional


logger = logging.getLogger("autodrome")
logger.propagate = False

_FORMATTER = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_SECRET_PATTERN = re.compile(
    r"(?i)\b(authorization|api[_-]?key|key|token)"
    r"\s*[:=]\s*(?:bearer\s+)?\S+"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+\S+")


def configure_logging(
    level: int = logging.INFO,
    *,
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 3,
) -> None:
    normalized_file = os.path.abspath(log_file) if log_file else None
    configuration = (level, normalized_file, max_bytes, backup_count)
    if getattr(logger, "_autodrome_configuration", None) == configuration:
        return

    for handler in list(logger.handlers):
        if getattr(handler, "_autodrome_handler", False):
            logger.removeHandler(handler)
            handler.close()

    stream_handler = logging.StreamHandler()
    stream_handler._autodrome_handler = True
    stream_handler.setFormatter(_FORMATTER)
    logger.addHandler(stream_handler)

    if normalized_file:
        file_handler = RotatingFileHandler(
            normalized_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler._autodrome_handler = True
        file_handler.setFormatter(_FORMATTER)
        logger.addHandler(file_handler)

    logger.setLevel(level)
    logger._autodrome_configuration = configuration


def safe_log_text(value: object, limit: int = 300) -> str:
    text = " ".join(str(value).split())
    text = _URL_PATTERN.sub("<url>", text)
    text = _SECRET_PATTERN.sub(r"\1=<redacted>", text)
    text = _BEARER_PATTERN.sub("Bearer <redacted>", text)
    return text if len(text) <= limit else f"{text[:limit]}..."


configure_logging()
