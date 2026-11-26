"""Logging with defensive secret redaction.

Secrets are already typed as SecretStr, but third-party libraries (httpx,
urllib3) may log URLs or headers. This filter scrubs anything that looks like
a credential before a record is emitted.
"""

import logging
import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(shpat|shpca|shppa|shpss)_[A-Za-z0-9]+"), r"\1_[REDACTED]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-[REDACTED]"),
    (
        re.compile(
            r"(?i)(apca-api-secret-key|apca-api-key-id|x-shopify-access-token|authorization|client_secret|access_token|api[_-]?key|apikey)"
            r"(['\"]?\s*[:=]\s*['\"]?)([^\s'\",&}]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+@"), r"\1[REDACTED]@"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        record.msg = redact(message)
        record.args = None
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # httpx logs full request lines at INFO; keep it quieter.
    logging.getLogger("httpx").setLevel(logging.WARNING)
