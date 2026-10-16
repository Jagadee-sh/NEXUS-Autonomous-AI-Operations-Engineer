"""Structured logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from nexus.config import settings

_SENSITIVE_KEYS = re.compile(
    r"(api[_-]?key|authorization|password|secret|token|credential|private[_-]?key)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"([\w.+-]+)@([\w-]+\.[\w.-]+)")
_PHONE_RE = re.compile(r"\b(\+?\d{1,3}[-. ]?)?(\(?\d{3}\)?[-. ]?)\d{3}[-. ]?\d{4}\b")


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEYS.search(key):
        return "***REDACTED***"
    if isinstance(value, str):
        value = _EMAIL_RE.sub(r"\1***@\2", value)
        value = _PHONE_RE.sub("***phone***", value)
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(key, v) for v in value]
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SENSITIVE_KEYS.sub("***REDACTED***", record.msg)
        for key in ("args",):
            args = getattr(record, key, None)
            if isinstance(args, dict):
                setattr(record, key, redact_value("args", args))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            payload["trace_id"] = trace_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact_value("extra", extra))
        return json.dumps(payload, default=str)


def setup_logging(level: str | None = None) -> None:
    log_level = (level or settings.log_level).upper()
    root = logging.getLogger()
    root.setLevel(log_level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    if settings.nexus_env == "production":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
        )
    handler.addFilter(RedactionFilter())
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
