"""Remove request query strings before Uvicorn records reach any handler.

WebSocket acceptance/rejection uses ``uvicorn.error`` rather than its HTTP
access logger. Filter both, retaining paths and the original argument shapes
required by Uvicorn's AccessFormatter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping


_REQUEST_QUERY = re.compile(r"((?:(?:https?|wss?)://)?/[^\s?\"'<>]*)\?[^\s\"'<>]*")
_REQUEST_TARGET = re.compile(r"^(?:(?:https?|wss?)://[^/]+)?/")
_FILTER_MARKER = "_zhiyuan_request_query_privacy"


def _redact(value: object) -> object:
    if isinstance(value, str):
        # Uvicorn supplies the complete target as one argument. Drop its whole
        # query, even if a raw HTTP peer sends quotes or whitespace in it.
        if _REQUEST_TARGET.match(value) and "?" in value:
            return value.split("?", 1)[0] + "?[redacted]"
        return _REQUEST_QUERY.sub(r"\1?[redacted]", value)
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _redact(item) for key, item in value.items()}
    return value


class UvicornRequestQueryFilter(logging.Filter):
    """Sanitize the record itself, including args used by structured handlers."""

    _zhiyuan_request_query_privacy = True

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name not in {"uvicorn.access", "uvicorn.error"}:
            return True
        record.msg = _redact(record.msg)
        record.args = _redact(record.args)
        # A preceding handler/filter may already have formatted the message.
        if "message" in record.__dict__:
            record.message = _redact(record.message)
        return True


def install_uvicorn_query_privacy() -> None:
    """Install once on the two Uvicorn emitters, without changing other logs."""
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(getattr(item, _FILTER_MARKER, False) for item in logger.filters):
            logger.addFilter(UvicornRequestQueryFilter())
