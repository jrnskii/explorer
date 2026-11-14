"""Application-owned stderr logging; never changes root or dependency logger levels."""

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4

from backend.application.telemetry import (
    TRACE,
    event,
    function_logger,
    operation,
    span_id,
    trace_id,
)

LEVELS = {
    "TRACE": TRACE,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class ContextFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = trace_id.get()
        record.span_id = span_id.get()
        return True


class LogFormatter(logging.Formatter):
    def __init__(self, output_format):
        super().__init__()
        self.output_format = output_format

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": "TRACE" if record.levelno == TRACE else record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
            "event": record.getMessage(),
            "fields": getattr(record, "event_fields", {}),
        }
        # Deliberately omit exception messages, source lines, locals and stack_info.
        if record.exc_info and record.exc_info[0]:
            payload["fields"] = {
                **payload["fields"],
                "error_type": record.exc_info[0].__name__,
            }
        if self.output_format == "json":
            return json.dumps(payload, ensure_ascii=True, allow_nan=False)
        fields = json.dumps(payload["fields"], ensure_ascii=True, allow_nan=False)
        message = json.dumps(payload["event"], ensure_ascii=True)
        return (
            f"{payload['timestamp']} {payload['level']} {record.name} "
            f"trace_id={payload['trace_id'] or '-'} span_id={payload['span_id'] or '-'} "
            f"{message} {fields}"
        )


def configure_logging(*, level=None, output_format=None):
    """Idempotently configure our handler, preserving host/test handlers."""
    selected = (level if level is not None else os.getenv("LOG_LEVEL", "INFO")).upper()
    output = (
        output_format if output_format is not None else os.getenv("LOG_FORMAT", "text")
    )
    if selected not in LEVELS:
        raise ValueError(
            "LOG_LEVEL must be TRACE, DEBUG, INFO, WARNING, ERROR or CRITICAL"
        )
    if output not in ("text", "json"):
        raise ValueError("LOG_FORMAT must be text or json")
    logging.addLevelName(TRACE, "TRACE")
    logger = logging.getLogger("backend")
    handlers = [logging.StreamHandler(sys.stderr)]
    if filename := os.getenv("LOG_FILE"):
        path = Path(filename).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"))
    for handler in list(logger.handlers):
        if getattr(handler, "_backend_owned", False):
            logger.removeHandler(handler)
            handler.close()
    for handler in handlers:
        handler._backend_owned = True
        handler.addFilter(ContextFilter())
        handler.setFormatter(LogFormatter(output))
        logger.addHandler(handler)
    logger.setLevel(LEVELS[selected])
    logger.propagate = False


def cli_entrypoint(function):
    """Configure each executable, correlate its run and report its exit status."""
    logger = function_logger(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        # Existing machine-oriented commands remain quiet unless logging is enabled.
        configure_logging(level=os.getenv("LOG_LEVEL", "WARNING"))
        token = trace_id.set(uuid4().hex)
        try:
            with operation(logger, "cli", level=logging.INFO):
                return run(*args, **kwargs)
        finally:
            trace_id.reset(token)

    def run(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
        except SystemExit as error:
            code = (
                error.code
                if isinstance(error.code, int)
                else (0 if error.code is None else 1)
            )
            event(
                logger,
                "cli.exit",
                level=logging.INFO if code == 0 else logging.ERROR,
                exit_code=code,
            )
            raise
        except BaseException as error:
            event(
                logger,
                "cli.error",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise
        event(
            logger,
            "cli.exit",
            level=logging.ERROR if result else logging.INFO,
            exit_code=result if isinstance(result, int) else 0,
        )
        return result

    return wrapped
