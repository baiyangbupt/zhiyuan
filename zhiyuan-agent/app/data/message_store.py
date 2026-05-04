"""Frontend render message persistence via internal message service."""

from __future__ import annotations

import json
from typing import Any

from app.util.internal_client import save_message


class MessageStore:
    """Persist websocket-visible messages to the legacy message table."""

    async def save_user_message(self, chat_session_id: str, content: str) -> int | None:
        result = await save_message(
            chat_session_id=chat_session_id,
            content=content,
            message_from=1,
            content_type="TEXT",
        )
        return result.get("data", {}).get("id")

    async def save_agent_message(
        self,
        chat_session_id: str,
        content: str,
        ws_type: str = "reply",
    ) -> int | None:
        if ws_type in {
            "interestAnalysisPopup",
            "planEditSelectPopup",
            "intentDetectSelectPopup",
            "intentConfirmPopup",
            "planningWorkspaceAction",
        }:
            # content is a JSON string; parse it to store as a dict
            try:
                popup_data = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                popup_data = {"type": ws_type, "title": content}
            popup_data["type"] = ws_type
            payload: str | dict[str, Any] = popup_data
            content_type = "CARD"
        elif ws_type == "card":
            payload = {
                "type": "card",
                "title": content,
            }
            content_type = "CARD"
        else:
            payload = content
            content_type = "TEXT"

        result = await save_message(
            chat_session_id=chat_session_id,
            content=payload,
            message_from=0,
            content_type=content_type,
        )
        return result.get("data", {}).get("id")


message_store = MessageStore()
