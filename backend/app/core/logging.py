"""Structured logging with request correlation IDs."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line so logs stay greppable in production."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                except (TypeError, ValueError):
                    value = repr(value)
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    """Human-friendly formatter used during local development."""

    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_ctx.get()
        suffix = " [" + rid[:8] + "]" if rid and rid != "-" else ""
        stamp = self.formatTime(record, "%H:%M:%S")
        base = "{0} {1:<7}{2} {3}: {4}".format(
            stamp, record.levelname, suffix, record.name, record.getMessage()
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(*, json_logs: bool = False, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else PlainFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn ships its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    # These libraries are extremely chatty below WARNING.
    for name in ("matplotlib", "numcodecs", "asyncio", "urllib3", "PIL"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
