from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class JsonRpcResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    jsonrpc: str = "2.0"
    id: int | str
    result: dict[str, Any] | None = None
    error: JsonRpcErrorModel | None = None

    @model_validator(mode="after")
    def _require_result_or_error(self) -> "JsonRpcResponse":
        if self.result is None and self.error is None:
            raise ValueError("result or error is required")
        return self


class JsonRpcErrorModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: int
    message: str
    data: Any = None


class Notification(BaseModel):
    model_config = ConfigDict(extra="allow")

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
