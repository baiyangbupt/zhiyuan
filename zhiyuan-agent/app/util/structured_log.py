from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("app.structured")


def log_event(event: str, **fields: Any) -> None:
    """Emit best-effort structured logs without affecting user flow."""
    try:
        logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))
    except Exception:
        logging.getLogger(__name__).warning("failed to emit structured log: event=%s", event, exc_info=True)
