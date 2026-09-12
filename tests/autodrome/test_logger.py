import logging
from logging.handlers import RotatingFileHandler

from autodrome.logger import configure_logging, logger, safe_log_text


def test_default_logging_uses_one_stream_without_propagation():
    configure_logging(logging.INFO)

    application_handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, "_autodrome_handler", False)
    ]
    assert logger.propagate is False
    assert len(application_handlers) == 1
    assert isinstance(application_handlers[0], logging.StreamHandler)
    assert not isinstance(application_handlers[0], logging.FileHandler)


def test_optional_file_logging_is_rotating_and_bounded(tmp_path):
    log_path = tmp_path / "autodrome.log"
    try:
        configure_logging(
            logging.DEBUG,
            log_file=str(log_path),
            max_bytes=1_024,
            backup_count=2,
        )

        file_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].maxBytes == 1_024
        assert file_handlers[0].backupCount == 2
        logger.info("test_event value=1")
        assert "test_event value=1" in log_path.read_text(encoding="utf-8")
    finally:
        configure_logging(logging.INFO)


def test_safe_log_text_removes_urls_controls_and_excess_length():
    value = (
        "failed https://example.test/path?token=url-secret\n"
        "api_key=plain-secret Authorization:Bearer bearer-secret "
        + ("x" * 500)
    )

    sanitized = safe_log_text(value, limit=60)

    assert "url-secret" not in sanitized
    assert "plain-secret" not in sanitized
    assert "bearer-secret" not in sanitized
    assert "https://" not in sanitized
    assert "\n" not in sanitized
    assert len(sanitized) == 63
