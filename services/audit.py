"""
services/audit.py  –  Audit logging.

Two sinks share the `audit` logger:
  - mem_handler: a bounded in-memory ring of the most recent N entries that
    the admin panel reads directly (``mem_handler.entries``).
  - file_handler: a rotating file at ``logs/audit.log`` so security and
    compliance events survive restarts and can be exported for review.

Callers should write **event-shaped** messages (e.g. ``"SECURITY – ..."``,
``"MEDICAL – report_id=42 status=APPROVED"``) — never raw diagnosis text or
patient PHI. The persistent log is the system of record; do not assume it
will be redacted later.
"""

import json
import logging
import logging.handlers
import os
from collections import deque

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "audit.log")
os.makedirs(LOG_DIR, exist_ok=True)


class _MemoryLogHandler(logging.Handler):
    """Keeps the last MAX_ENTRIES log messages in a deque for the admin panel."""

    MAX_ENTRIES = 200

    def __init__(self):
        super().__init__()
        # deque(maxlen=...) keeps the ring O(1) on both ends.
        self.entries: deque[str] = deque(maxlen=self.MAX_ENTRIES)

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(self.format(record))


class _JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for the durable file sink.

    Emits one JSON object per line (`ndjson`) so the file is grep-able and
    can be tailed straight into ELK / Loki / Splunk without a custom parser.
    """

    # ``datefmt`` is used by ``formatTime`` when set. ISO 8601 with seconds
    # is unambiguous across timezones and easy to sort lexicographically.
    default_datefmt = "%Y-%m-%dT%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      self.formatTime(record, self.default_datefmt),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# Human-readable formatter for the admin panel (rendered as plain text in
# the live log widget). Sub-second precision isn't useful for an operator
# scanning the list.
_human_formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

mem_handler = _MemoryLogHandler()
mem_handler.setFormatter(_human_formatter)

# Rotate at ~1 MB, keep 10 backups (≈10 MB total). The file is the durable
# record; mem_handler is purely for the live admin view.
file_handler = logging.handlers.RotatingFileHandler(
    LOG_PATH, maxBytes=1_000_000, backupCount=10, encoding="utf-8"
)
file_handler.setFormatter(_JSONFormatter())

audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)
audit_logger.addHandler(mem_handler)
audit_logger.addHandler(file_handler)
audit_logger.propagate = False
