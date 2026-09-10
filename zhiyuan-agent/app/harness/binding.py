from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.admission.facts import AdmissionFactError, canonical_admission_mode


class BindingError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def generate_opaque_handle() -> str:
    """Create a short-lived credential suitable for a server-side binding.

    The handle is intentionally opaque and URL-safe.  Callers must keep the
    cleartext value in the gateway process only; the backend stores its hash.
    """

    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ToolContext:
    thread_id: str
    tenant_id: str
    session_id: str
    user_id: str
    admission_mode: str = "major"
    allowed_capabilities: frozenset[str] = field(default_factory=frozenset)
    model_identity_override: str = ""
    snapshot_version: int | None = None


@dataclass(frozen=True)
class ThreadBinding:
    thread_id: str
    tenant_id: str
    session_id: str
    user_id: str
    allowed_capabilities: frozenset[str] = field(default_factory=frozenset)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    opaque_handle: str = field(default="", repr=False, compare=False)
    admission_mode: str = "major"
    # Bound by the Gateway to the authoritative Snapshot injected into this turn.
    # It is intentionally not derived from model-provided tool arguments.
    snapshot_version: int | None = None

    @classmethod
    def create(
        cls,
        *,
        thread_id: str,
        tenant_id: str,
        session_id: str,
        user_id: str,
        allowed_capabilities: set[str] | frozenset[str],
        admission_mode: str = "major",
        snapshot_version: int | None = None,
        expires_at: datetime | None = None,
    ) -> "ThreadBinding":
        return cls(
            thread_id=thread_id,
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            allowed_capabilities=frozenset(allowed_capabilities),
            admission_mode=admission_mode,
            snapshot_version=snapshot_version,
            expires_at=expires_at,
            opaque_handle=generate_opaque_handle(),
        )

    def __post_init__(self) -> None:
        # ``frozen=True`` must also protect the capability allowlist from
        # mutation after construction.
        object.__setattr__(self, "allowed_capabilities", frozenset(self.allowed_capabilities))
        try:
            object.__setattr__(self, "admission_mode", canonical_admission_mode(self.admission_mode))
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
        if self.snapshot_version is not None:
            try:
                snapshot_version = int(self.snapshot_version)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid_snapshot_version") from exc
            if isinstance(self.snapshot_version, bool) or snapshot_version < 0:
                raise ValueError("invalid_snapshot_version")
            object.__setattr__(self, "snapshot_version", snapshot_version)

    def _validate_active(self) -> None:
        now = datetime.now(timezone.utc)
        if self.revoked_at is not None:
            raise BindingError("binding_revoked")
        if self.expires_at is not None and self.expires_at <= now:
            raise BindingError("binding_expired")

    def authorize(self, capability: str) -> None:
        self._validate_active()
        if capability not in self.allowed_capabilities:
            raise BindingError("capability_denied")

    def context(self, *, model_identity_override: str = "") -> ToolContext:
        self._validate_active()
        return ToolContext(
            thread_id=self.thread_id,
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            user_id=self.user_id,
            admission_mode=self.admission_mode,
            allowed_capabilities=frozenset(self.allowed_capabilities),
            model_identity_override=model_identity_override,
            snapshot_version=self.snapshot_version,
        )

    def resolve_tool_context(self, model_payload: dict[str, Any] | None = None) -> ToolContext:
        if model_payload is not None and not isinstance(model_payload, dict):
            raise BindingError("invalid_model_payload")
        payload = model_payload or {}
        identity_keys = {"threadId", "tenantId", "sessionId", "userId"}
        supplied = {key: payload[key] for key in identity_keys if key in payload}
        override = "ignored" if supplied else ""
        return self.context(model_identity_override=override)
