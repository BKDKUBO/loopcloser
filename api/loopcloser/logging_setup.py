"""Structured JSON logging for Cloud Logging, with Error Reporting support.

Each log line is one JSON object with "severity" and "message". Lines with a
stack trace carry the ReportedErrorEvent type, so Cloud Error Reporting groups
them automatically (no third-party error tracker needed). We log ids, never PHI.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
trace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace", default=None)

ERROR_EVENT_TYPE = "type.googleapis.com/google.devtools.clouderrorreporting.v1beta1.ReportedErrorEvent"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
            "serviceContext": {"service": "loopcloser-api", "version": os.getenv("K_REVISION", "dev")},
        }
        rid = request_id_var.get()
        if rid:
            entry["request_id"] = rid
        trace = trace_var.get()
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if trace and project:
            entry["logging.googleapis.com/trace"] = f"projects/{project}/traces/{trace}"
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            entry.update(extra)
        if record.exc_info:
            entry["@type"] = ERROR_EVENT_TYPE
            entry["stack_trace"] = "".join(traceback.format_exception(*record.exc_info))
            entry["message"] = f"{entry['message']}\n{entry['stack_trace']}"
        return json.dumps(entry, default=str)


def setup_logging(level: str | None = None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root.addHandler(h)
    root.setLevel(level or os.getenv("LOG_LEVEL", "INFO"))
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = False
