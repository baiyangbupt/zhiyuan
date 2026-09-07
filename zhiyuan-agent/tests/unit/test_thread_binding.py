from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.harness.binding import BindingError, ThreadBinding, generate_opaque_handle
from app.mcp_server.context import TrustedToolContext


def test_binding_keeps_server_identity_when_model_supplies_conflicting_fields() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    context = binding.resolve_tool_context(
        {"threadId": "thr_test", "sessionId": "session-2", "userId": "user-2"}
    )

    assert context.session_id == "session-1"
    assert context.user_id == "user-1"
    assert context.model_identity_override == "ignored"


def test_binding_rejects_non_object_model_identity_payload() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
    )

    with pytest.raises(BindingError, match="invalid_model_payload"):
        binding.resolve_tool_context(["session-2"])  # type: ignore[arg-type]


def test_expired_binding_fails_closed() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(BindingError, match="binding_expired"):
        binding.authorize("catalog.search_schools")


def test_revoked_binding_fails_closed() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        revoked_at=datetime.now(timezone.utc),
    )

    with pytest.raises(BindingError, match="binding_revoked"):
        binding.authorize("catalog.search_schools")


def test_context_generation_fails_closed_for_revoked_binding() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
        revoked_at=datetime.now(timezone.utc),
    )

    with pytest.raises(BindingError, match="binding_revoked"):
        binding.context()


def test_context_generation_fails_closed_for_expired_binding() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(BindingError, match="binding_expired"):
        binding.context()


def test_context_rejects_capability_outside_allowlist() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    with pytest.raises(BindingError, match="capability_denied"):
        binding.authorize("plan.propose_changes")


def test_trusted_tool_context_is_immutable_from_model_payload() -> None:
    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    context = TrustedToolContext.from_binding(binding)

    resolved = context.with_model_arguments({"sessionId": "session-2"})

    assert resolved.session_id == "session-1"
    assert resolved.model_identity_override == "ignored"


def test_generate_opaque_handle_is_urlsafe_and_not_reused() -> None:
    first = generate_opaque_handle()
    second = generate_opaque_handle()

    assert len(first) >= 32
    assert first != second
    assert all(character.isalnum() or character in "-_" for character in first)


def test_gateway_binding_keeps_opaque_handle_out_of_tool_context_and_repr() -> None:
    binding = ThreadBinding.create(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities={"catalog.search_schools"},
    )

    assert len(binding.opaque_handle) >= 32
    assert binding.opaque_handle not in repr(binding)
    assert not hasattr(binding.context(), "opaque_handle")
