"""Redaction applied to logs, audit events and error details. Never log raw resumes,
API keys, passwords, cookies or full forms."""
import re
from typing import Any

SENSITIVE_KEYS = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|cookie|set-cookie|session|bearer)", re.I)
_PATTERNS = [
    (re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\d)(\+?\d[\d\s().-]{8,}\d)(?!\d)"), "[REDACTED_PHONE]"),
]
_BIG = 500


def redact_text(s: str) -> str:
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    if len(s) > _BIG:
        s = s[:_BIG] + f"...[truncated {len(s) - _BIG} chars]"
    return s


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if SENSITIVE_KEYS.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj
