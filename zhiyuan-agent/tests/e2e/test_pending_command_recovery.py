"""Opt-in real backend recovery test for idempotent pending commands."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse
import uuid

import aiohttp
import pytest


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("RUN_PENDING_COMMAND_RECOVERY_E2E") != "1",
        reason="需要本地 Backend/MySQL，设置 RUN_PENDING_COMMAND_RECOVERY_E2E=1 后运行",
    ),
]

BACKEND_URL = os.getenv("PENDING_COMMAND_E2E_BACKEND_URL", "http://127.0.0.1:18082").rstrip("/")
DB_HOST = os.getenv("PENDING_COMMAND_E2E_DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("PENDING_COMMAND_E2E_DB_PORT", "3306")
DB_USER = os.getenv("PENDING_COMMAND_E2E_DB_USER", "root")
DB_PASSWORD = os.getenv("PENDING_COMMAND_E2E_DB_PASSWORD", "12345678")
DB_NAME = os.getenv("PENDING_COMMAND_E2E_DB_NAME", "sales_bot")
SOURCE_SESSION_ID = int(os.getenv("PENDING_COMMAND_E2E_SOURCE_SESSION_ID", "9904894"))
TARGET_SESSION_ID = int(os.getenv("PENDING_COMMAND_E2E_TARGET_SESSION_ID", "990499995"))
PENDING_ID = "pending-command-recovery-e2e"
COMMAND_TYPE = "apply_constraint_and_regenerate"
OPERATION_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zhiyuan:{PENDING_ID}:{COMMAND_TYPE}"))
RESTART_READY_FILE = os.getenv("PENDING_COMMAND_E2E_RESTART_READY_FILE")
RESTART_RESUME_FILE = os.getenv("PENDING_COMMAND_E2E_RESTART_RESUME_FILE")


def _mysql(sql: str) -> str:
    result = subprocess.run(
        [
            "mysql",
            f"-h{DB_HOST}",
            f"-P{DB_PORT}",
            f"-u{DB_USER}",
            f"-p{DB_PASSWORD}",
            "-N",
            "-B",
            DB_NAME,
            "-e",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


async def _post(path: str, payload: dict, *, timeout: float = 10.0) -> dict:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.post(f"{BACKEND_URL}{path}", json=payload) as response:
            return await response.json()


def _cleanup() -> None:
    _mysql(
        f"DELETE FROM assistant_planning_pending_command WHERE chat_session_id={TARGET_SESSION_ID};"
        f"DELETE FROM assistant_chat_session_pending_confirmation WHERE chat_session_id={TARGET_SESSION_ID};"
        "DELETE FROM assistant_chat_session_extra_data "
        f"WHERE chat_session_id={TARGET_SESSION_ID} AND data_key='planningState';"
    )


async def _wait_for_succeeded_operation() -> None:
    for _ in range(100):
        status = _mysql(
            "SELECT status FROM assistant_planning_pending_command "
            f"WHERE operation_id='{OPERATION_ID}' LIMIT 1;"
        )
        if status == "succeeded":
            return
        await asyncio.sleep(0.1)
    raise AssertionError("timed out waiting for succeeded operation after client disconnect")


def _backend_listener_pids() -> set[str]:
    port = urlparse(BACKEND_URL).port
    assert port is not None, f"backend URL must include a port: {BACKEND_URL}"
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


async def _wait_for_backend_restart() -> None:
    if RESTART_READY_FILE or RESTART_RESUME_FILE:
        assert RESTART_READY_FILE and RESTART_RESUME_FILE, (
            "restart barrier requires both PENDING_COMMAND_E2E_RESTART_READY_FILE "
            "and PENDING_COMMAND_E2E_RESTART_RESUME_FILE"
        )
        ready_file = Path(RESTART_READY_FILE)
        resume_file = Path(RESTART_RESUME_FILE)
        old_listener_pids = _backend_listener_pids()
        assert old_listener_pids, f"no backend listener found before restart: {BACKEND_URL}"
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.write_text(
            f"operationId={OPERATION_ID}\noldListenerPids={','.join(sorted(old_listener_pids))}\n",
            encoding="ascii",
        )
        print(
            f"READY_FOR_RESTART operationId={OPERATION_ID} "
            f"oldListenerPids={','.join(sorted(old_listener_pids))}",
            flush=True,
        )
        timeout = float(os.getenv("PENDING_COMMAND_E2E_RESTART_TIMEOUT_SECONDS", "180"))
        for _ in range(max(1, int(timeout * 10))):
            if resume_file.exists():
                new_listener_pids = _backend_listener_pids()
                assert new_listener_pids, f"no backend listener found after restart: {BACKEND_URL}"
                assert old_listener_pids.isdisjoint(new_listener_pids), (
                    "restart barrier resumed without replacing the backend process: "
                    f"old={sorted(old_listener_pids)} new={sorted(new_listener_pids)}"
                )
                return
            await asyncio.sleep(0.1)
        raise AssertionError(f"timed out waiting for restart resume marker: {resume_file}")

    restart_pause = float(os.getenv("PENDING_COMMAND_E2E_RESTART_PAUSE_SECONDS", "0"))
    if restart_pause > 0:
        await asyncio.sleep(restart_pause)


async def test_pending_command_recovers_after_response_loss_and_lease_takeover():
    marker_files = [Path(path) for path in (RESTART_READY_FILE, RESTART_RESUME_FILE) if path]
    for marker_file in marker_files:
        marker_file.unlink(missing_ok=True)
    _cleanup()
    try:
        _mysql(
            "INSERT INTO assistant_chat_session_extra_data "
            "(chat_session_id,data_key,data_type,data_value,data_version) "
            f"SELECT {TARGET_SESSION_ID},data_key,data_type,"
            f"JSON_SET(data_value,'$.sessionId',{TARGET_SESSION_ID}),data_version "
            "FROM assistant_chat_session_extra_data "
            f"WHERE chat_session_id={SOURCE_SESSION_ID} AND data_key='planningState' "
            "ORDER BY data_version DESC,id DESC LIMIT 1;"
        )
        source_version = int(
            _mysql(
                "SELECT JSON_UNQUOTE(JSON_EXTRACT(data_value,'$.version')) "
                "FROM assistant_chat_session_extra_data "
                f"WHERE chat_session_id={TARGET_SESSION_ID} AND data_key='planningState';"
            )
        )

        created = await _post(
            "/gaotu-assistant-bot/inner/chat/1/session/pending",
            {
                "chatSessionId": TARGET_SESSION_ID,
                "pendingId": PENDING_ID,
                "expectedRevision": 0,
                "kind": "intent_change",
                "actionFamily": COMMAND_TYPE,
                "dataValue": {"pendingId": PENDING_ID, "status": "active"},
            },
        )
        assert created["code"] == 0

        claim_a = "recovery-e2e-claim-a"
        claimed = await _post(
            "/gaotu-assistant-bot/inner/chat/1/session/pending/resolve",
            {
                "chatSessionId": TARGET_SESSION_ID,
                "pendingId": PENDING_ID,
                "expectedRevision": 1,
                "action": "confirm",
                "claimToken": claim_a,
            },
        )
        assert claimed["data"]["transitionApplied"] is True

        command = {
            "operationId": OPERATION_ID,
            "pendingId": PENDING_ID,
            "claimToken": claim_a,
            "expectedPlanVersion": source_version,
            "commandType": COMMAND_TYPE,
            "constraintUpdate": {
                "intentMode": "preference",
                "regionPreferences": {"positive": ["杭州"], "negative": []},
            },
            "regenerateOrderedPlan": False,
            "unitIds": [],
            "volunteerIds": [],
        }
        with pytest.raises((asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
            await _post(
                "/gaotu-assistant-bot/inner/planning/1/session/pending-command/execute"
                f"?chatSessionId={TARGET_SESSION_ID}",
                command,
                timeout=0.01,
            )
        await _wait_for_succeeded_operation()

        committed_version = int(
            _mysql(
                "SELECT JSON_UNQUOTE(JSON_EXTRACT(data_value,'$.version')) "
                "FROM assistant_chat_session_extra_data "
                f"WHERE chat_session_id={TARGET_SESSION_ID} AND data_key='planningState';"
            )
        )
        assert committed_version == source_version + 1

        await _wait_for_backend_restart()

        _mysql(
            "UPDATE assistant_chat_session_pending_confirmation "
            "SET claim_expires_at=DATE_SUB(NOW(),INTERVAL 1 SECOND) "
            f"WHERE chat_session_id={TARGET_SESSION_ID};"
        )
        claim_b = "recovery-e2e-claim-b"
        reclaimed = await _post(
            "/gaotu-assistant-bot/inner/chat/1/session/pending/resolve",
            {
                "chatSessionId": TARGET_SESSION_ID,
                "pendingId": PENDING_ID,
                "expectedRevision": 2,
                "action": "confirm",
                "claimToken": claim_b,
            },
        )
        assert reclaimed["data"]["transitionApplied"] is True
        assert reclaimed["data"]["revision"] == 3

        replay = await _post(
            "/gaotu-assistant-bot/inner/planning/1/session/pending-command/execute"
            f"?chatSessionId={TARGET_SESSION_ID}",
            {**command, "claimToken": claim_b},
        )
        assert replay["code"] == 0
        assert replay["data"]["replayed"] is True
        assert replay["data"]["resultPlanVersion"] == committed_version

        completed = await _post(
            "/gaotu-assistant-bot/inner/chat/1/session/pending/resolve",
            {
                "chatSessionId": TARGET_SESSION_ID,
                "pendingId": PENDING_ID,
                "expectedRevision": 3,
                "action": "complete",
                "claimToken": claim_b,
                "resultCode": "recovery_e2e_passed",
            },
        )
        assert completed["data"]["status"] == "applied"
        assert completed["data"]["revision"] == 4
        assert int(
            _mysql(
                "SELECT JSON_UNQUOTE(JSON_EXTRACT(data_value,'$.version')) "
                "FROM assistant_chat_session_extra_data "
                f"WHERE chat_session_id={TARGET_SESSION_ID} AND data_key='planningState';"
            )
        ) == committed_version
    finally:
        _cleanup()
        for marker_file in marker_files:
            marker_file.unlink(missing_ok=True)
