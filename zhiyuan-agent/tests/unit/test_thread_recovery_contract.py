import pytest

from app.gateway.thread_recovery import (
    CurrentBinding,
    ThreadRecovery,
    ThreadRecoveryError,
    compose_current_binding_lookup,
)
from app.gateway.ui_events import SessionKey


KEY = SessionKey("7", "101")


@pytest.mark.parametrize("payload", [
    {"code": False, "data": None},
    {"code": 0.0, "data": None},
    {"data": None},
    {"code": 0},
    {"code": 0, "data": None, "success": False},
    {"code": 0, "data": None, "success": 1},
    {"code": 0, "data": None, "error": "failed"},
    {"code": 0, "data": None, "errors": []},
    {"code": 0, "data": None, "failed": True},
    {"code": 0, "data": "invalid-binding"},
    {"code": 0, "data": []},
    {"code": 0, "data": {"code": 0, "data": None}},
    {"code": 503, "data": None},
])
@pytest.mark.parametrize("composed", [False, True])
async def test_untrusted_lookup_never_falls_back_resumes_or_creates(payload, composed):
    operations = []

    async def backend(tenant_id, session_id):
        return payload

    class Registry:
        def latest_for_session(self, tenant_id, session_id):
            operations.append("registry")
            return {"threadId": "thr-local", "tenantId": 7, "chatSessionId": 101}

    async def resume(thread_id):
        operations.append("resume")

    async def create():
        operations.append("create")
        return {"thread": {"id": "thr-new"}}

    lookup = compose_current_binding_lookup(backend, Registry()) if composed else backend
    recovery = ThreadRecovery(lookup=lookup, resume=resume, create=create)
    with pytest.raises(ThreadRecoveryError):
        await recovery.load_or_resume(KEY)
    assert operations == []


@pytest.mark.parametrize("changes", [
    {"tenantId": None}, {"chatSessionId": None},
    {"tenantId": ""}, {"chatSessionId": ""},
    {"tenantId": True}, {"chatSessionId": True},
    {"tenantId": 7.0}, {"chatSessionId": [101]},
    {"tenantId": 0}, {"chatSessionId": -1},
    {"tenantId": "０７"}, {"chatSessionId": "1.01"},
    {"tenantId": "9223372036854775808"},
    {"tenantId": " 7"}, {"chatSessionId": "0101"},
    {"tenantId": "other-tenant"}, {"chatSessionId": "other-session"},
    {"threadId": True}, {"threadId": 123},
    {"threadId": []}, {"threadId": "   "}, {"threadId": " thr-old"},
])
@pytest.mark.parametrize("local", [False, True])
async def test_invalid_binding_identity_never_resumes_or_creates(changes, local):
    payload = {"threadId": "thr-old", "tenantId": 7, "chatSessionId": 101}
    payload.update(changes)
    operations = []

    async def backend(tenant_id, session_id):
        return {"code": 0, "data": None if local else payload}

    class Registry:
        def latest_for_session(self, tenant_id, session_id):
            return payload

    async def resume(thread_id):
        operations.append("resume")

    async def create():
        operations.append("create")
        return {"thread": {"id": "thr-new"}}

    recovery = ThreadRecovery(
        lookup=compose_current_binding_lookup(backend, Registry()),
        resume=resume, create=create,
    )
    with pytest.raises(ThreadRecoveryError):
        await recovery.load_or_resume(KEY)
    assert operations == []


@pytest.mark.parametrize("scope", [{}, {"tenantId": 7}, {"chatSessionId": 101}])
async def test_missing_binding_scope_is_not_a_new_or_resumable_session(scope):
    operations = []

    async def lookup(tenant_id, session_id):
        return {"code": 0, "data": {"threadId": "thr-unscoped", **scope}}

    async def resume(thread_id):
        operations.append("resume")

    async def create():
        operations.append("create")
        return {"thread": {"id": "thr-new"}}

    with pytest.raises(ThreadRecoveryError):
        await ThreadRecovery(lookup=lookup, resume=resume, create=create).load_or_resume(KEY)
    assert operations == []


@pytest.mark.parametrize("tenant_id,session_id", [("", "101"), ("7", ""), ("", "")])
def test_empty_binding_identity_cannot_match_a_session(tenant_id, session_id):
    binding = CurrentBinding("thr-old", tenant_id, session_id)
    assert binding.belongs_to(KEY) is False


@pytest.mark.parametrize("envelope", [False, True])
async def test_complete_scoped_binding_can_be_resumed(envelope):
    payload = {"threadId": "thr-old", "tenantId": 7, "chatSessionId": "101"}
    resumed = []

    async def lookup(tenant_id, session_id):
        return {"code": 0, "data": payload} if envelope else payload

    async def create():
        pytest.fail("an existing binding must not create a thread")

    recovery = ThreadRecovery(lookup=lookup, resume=resumed.append, create=create)
    assert await recovery.load_or_resume(KEY) == "thr-old"
    assert resumed == ["thr-old"]


@pytest.mark.parametrize("value", [1, "1", 9223372036854775807, "9223372036854775807"])
def test_scoped_binding_supports_canonical_java_long_ids(value):
    binding = CurrentBinding.from_payload({
        "threadId": "thr-old", "tenantId": value, "chatSessionId": value,
    })
    assert binding is not None
    assert binding.belongs_to(SessionKey(str(value), str(value)))
