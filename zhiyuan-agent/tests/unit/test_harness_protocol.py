from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.harness.protocol import JsonRpcError, JsonRpcResponse, Notification


def test_json_rpc_response_accepts_result_or_error() -> None:
    result = JsonRpcResponse.model_validate({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    error = JsonRpcResponse.model_validate(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32000, "message": "failed"},
        }
    )

    assert result.result == {"ok": True}
    assert error.error is not None
    assert error.error.code == -32000


def test_json_rpc_response_rejects_missing_result_and_error() -> None:
    with pytest.raises(ValidationError, match="result or error"):
        JsonRpcResponse.model_validate({"jsonrpc": "2.0", "id": 1})


def test_notification_requires_method() -> None:
    notification = Notification.model_validate(
        {"jsonrpc": "2.0", "method": "thread/started", "params": {"threadId": "thr-1"}}
    )
    assert notification.method == "thread/started"
    assert notification.params["threadId"] == "thr-1"


def test_json_rpc_error_is_exception_with_code_and_data() -> None:
    error = JsonRpcError(code=-32001, message="overloaded", data={"retryable": True})
    assert str(error) == "overloaded"
    assert error.code == -32001
    assert error.data == {"retryable": True}
