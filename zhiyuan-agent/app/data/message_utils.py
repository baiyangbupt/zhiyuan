"""Message formatting utilities."""

from __future__ import annotations

from typing import Any


def pydantic_ai_messages_to_dicts(messages: list[Any]) -> list[dict]:
    """Convert pydantic-ai ModelMessage list to simple dicts.

    Extracts user/assistant text from ModelRequest/ModelResponse objects
    into [{"role": "user", "content": "..."}, ...] format.

    Args:
        messages: pydantic-ai all_messages() output (ModelRequest/ModelResponse list)

    Returns:
        List of {"role", "content"} dicts
    """
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

    result: list[dict] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    result.append({"role": "user", "content": part.content})
        elif isinstance(msg, ModelResponse):
            texts = [p.content for p in msg.parts if isinstance(p, TextPart)]
            if texts:
                result.append({"role": "assistant", "content": "".join(texts)})
    return result


def format_messages(messages: list[dict]) -> str:
    """Format message list into readable text.

    Args:
        messages: List of message dicts with 'role', 'content', and optional 'clicked'

    Returns:
        Formatted string with "学生: ..." / "规划师: ..." format
    """
    # Find last message with clicked=False
    last_false_index = -1
    for idx, msg in enumerate(messages):
        if msg.get("clicked") is not None and not msg.get("clicked"):
            last_false_index = idx

    chat_history = "\n=== 对话历史开始 ===\n\n"
    for idx, msg in enumerate(messages):
        if msg.get("clicked") is not None:
            # Skip non-last False clicked messages
            if not msg.get("clicked") and idx != last_false_index:
                chat_history += "规划师: [规划师提出了建议，但是用户未回应，对内容遮盖掉，避免影响输出。]\n\n"
                continue
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            chat_history += f"学生: {content}\n\n"
        elif role == "assistant":
            chat_history += f"规划师: {content}\n\n"
    chat_history += "=== 对话历史结束 ===\n"
    return chat_history


def trim_last_n_messages(messages: list[dict], n: int) -> list[dict]:
    """Trim to last n messages after removing first two welcome messages.

    Args:
        messages: Original message list
        n: Number of messages to keep

    Returns:
        Trimmed message list
    """
    # Remove first two welcome messages
    # if len(messages) > 2:
    #     messages = messages[2:]
    # else:
    #     return messages

    # Return last n messages
    if len(messages) <= n:
        return messages

    return messages[-n:]
