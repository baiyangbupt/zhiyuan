"""Helpers for JSON-based extraction outputs.

Avoids provider-specific structured-output tool forcing such as
`tool_choice=required`, which some OpenAI-compatible backends don't support.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def parse_extraction_json(raw_text: str, schema: type[SchemaT]) -> SchemaT:
    """Parse model text output into the target schema.

    Supports plain JSON and fenced ```json blocks.
    """
    text = raw_text.strip()
    if not text:
        raise ValueError("Empty extraction output")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()
    elif not text.startswith("{"):
        object_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if object_match:
            text = object_match.group(1).strip()

    data = json.loads(text)
    return schema.model_validate(data)
