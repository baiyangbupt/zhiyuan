"""Real WebSocket e2e scenarios for agent dialog quality and latency.

These tests call the local compat WebSocket endpoint and may trigger real LLM
usage. They are opt-in because they depend on running Backend/Agent services
and a usable model provider.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("RUN_AGENT_DIALOG_E2E") != "1",
        reason="需要本地 Agent/Backend 和真实 LLM，设置 RUN_AGENT_DIALOG_E2E=1 后运行",
    ),
]

RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
EFFECT_PERF_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_effect_perf_cases.json"
DEFAULT_HISTORY_DB = Path(__file__).resolve().parents[2] / "data" / "chat_history.db"

SPEC = importlib.util.spec_from_file_location("dialog_regression_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


async def test_agent_dialog_effect_and_performance_smoke():
    cases_path = Path(os.getenv("AGENT_DIALOG_E2E_CASES") or EFFECT_PERF_CASES_PATH)
    cases = runner._load_cases(str(cases_path))
    if os.getenv("AGENT_DIALOG_E2E_CLEAR_HISTORY", "1") != "0":
        runner._clear_history(DEFAULT_HISTORY_DB, runner._case_session_ids(cases))

    await runner._run_cases(
        os.getenv("AGENT_DIALOG_E2E_URL") or runner.DEFAULT_URL,
        os.getenv("AGENT_DIALOG_E2E_USER_ID") or "dialog-effect-perf-user",
        cases,
        assert_plan_style=True,
        open_timeout=float(os.getenv("AGENT_DIALOG_E2E_OPEN_TIMEOUT", "30")),
        response_timeout=float(os.getenv("AGENT_DIALOG_E2E_RESPONSE_TIMEOUT", "180")),
        metrics_output=os.getenv("AGENT_DIALOG_E2E_METRICS_OUTPUT") or None,
        history_db=os.getenv("AGENT_DIALOG_E2E_HISTORY_DB") or str(DEFAULT_HISTORY_DB),
    )
