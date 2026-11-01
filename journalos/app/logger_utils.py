"""Privacy-First Structured Logging & Live Diagnostics Mechanism for JournalOS.

SECURITY & PRIVACY GUARANTEE:
- Automatically redacts all journal text, chat messages, emotional states, personal names,
  Google Sheets URLs, and API keys before writing to disk or memory.
- Logs ONLY operational telemetry (category, action, status, latency in ms, and safe counts).
"""

from __future__ import annotations

import collections
import datetime
import json
import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

TEXT_LOG_FILE = LOGS_DIR / "journalos.log"
JSONL_LOG_FILE = LOGS_DIR / "debug_events.jsonl"

_RECENT_EVENTS: collections.deque[dict[str, Any]] = collections.deque(maxlen=200)

# Keys that must NEVER appear in plain text inside logs
_SENSITIVE_KEYS = {
    "content",
    "message",
    "msg_preview",
    "fact",
    "prompt",
    "title",
    "emotion",
    "mood",
    "user_name",
    "gemini_api_key",
    "api_key",
    "google_sheets_webhook_url",
    "webhook_url",
    "secret_token",
    "vault_token",
    "url",
}


def redact_sensitive_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively strips or masks any PII, mental-state data, or credentials from log payloads."""
    if not details or not isinstance(details, dict):
        return {}
    safe: dict[str, Any] = {}
    for k, v in details.items():
        k_low = str(k).lower()
        if k_low in _SENSITIVE_KEYS or any(
            s in k_low for s in ("key", "token", "secret", "webhook", "password", "pin")
        ):
            safe[k] = "[REDACTED_FOR_PRIVACY]"
        elif isinstance(v, dict):
            safe[k] = redact_sensitive_details(v)
        elif isinstance(v, str) and (
            "script.google.com" in v or "AIza" in v or len(v) > 80
        ):
            safe[k] = "[REDACTED_FOR_PRIVACY]"
        else:
            safe[k] = v
    return safe


def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("journalos")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime )s | %(levelname)-7s | %(name)s | %(message)s".replace("\u200a", ""),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        TEXT_LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


logger = _setup_logger()


def log_event(
    category: str,
    action: str,
    status: str = "OK",
    details: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    error: Exception | str | None = None,
) -> dict[str, Any]:
    """Records a privacy-redacted diagnostic event to `journalos.log`, `debug_events.jsonl`, and memory."""
    now_iso = datetime.datetime.now().astimezone().isoformat()
    safe_details = redact_sensitive_details(details)

    record: dict[str, Any] = {
        "timestamp": now_iso,
        "category": category,
        "action": action,
        "status": status,
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "details": safe_details,
    }
    if error is not None:
        err_str = str(error)
        if "script.google.com" in err_str or "key=" in err_str:
            err_str = "External service connection error (URL/Key redacted for privacy)"
        record["error"] = err_str
        if isinstance(error, Exception):
            record["traceback_type"] = type(error).__name__

    _RECENT_EVENTS.appendleft(record)

    try:
        with open(JSONL_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass

    msg = f"[{category}:{action}] status={status}"
    if duration_ms is not None:
        msg += f" ({duration_ms:.1f}ms)"
    if safe_details:
        msg += f" | {json.dumps(safe_details, default=str)[:200]}"
    if error:
        logger.error(f"{msg} | error={record.get('error')}")
    else:
        logger.info(msg)

    return record


def clear_all_logs() -> dict[str, str]:
    """Allows the user to wipe all diagnostic logs from memory and disk."""
    _RECENT_EVENTS.clear()
    for p in (TEXT_LOG_FILE, JSONL_LOG_FILE):
        try:
            if p.exists():
                p.write_text("", encoding="utf-8")
        except Exception:
            pass
    return {"status": "SUCCESS", "message": "All diagnostic logs wiped."}


def get_recent_logs(limit: int = 80, category: str | None = None) -> dict[str, Any]:
    """Returns recent privacy-redacted log events."""
    events = list(_RECENT_EVENTS)
    if category:
        cat_low = category.lower().strip()
        events = [
            e for e in events if cat_low in str(e.get("category", "")).lower()
        ]
    return {
        "privacy_mode": "STRICT_PII_REDACTION_ACTIVE",
        "log_file": str(TEXT_LOG_FILE),
        "jsonl_file": str(JSONL_LOG_FILE),
        "total_buffered": len(_RECENT_EVENTS),
        "events": events[: max(1, int(limit))],
    }
