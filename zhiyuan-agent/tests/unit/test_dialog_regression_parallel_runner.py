import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_parallel_runner.py"
SPEC = importlib.util.spec_from_file_location("dialog_regression_parallel_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
parallel_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parallel_runner
SPEC.loader.exec_module(parallel_runner)


def test_parallel_runner_rejects_output_dir_with_existing_metrics(tmp_path):
    metrics_path = tmp_path / "case.metrics.json"
    metrics_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already contains regression artifacts"):
        parallel_runner._ensure_output_dir_ready(tmp_path, reuse_output_dir=False)


def test_parallel_runner_allows_explicit_output_dir_reuse(tmp_path):
    metrics_path = tmp_path / "case.metrics.json"
    metrics_path.write_text("{}\n", encoding="utf-8")

    parallel_runner._ensure_output_dir_ready(tmp_path, reuse_output_dir=True)

    assert tmp_path.exists()


def test_parallel_runner_passes_history_db_to_child_runner(tmp_path):
    case_file = tmp_path / "cases.json"
    case_file.write_text("[]\n", encoding="utf-8")
    history_db = tmp_path / "history.sqlite"
    recorded: dict[str, object] = {}

    class _Proc:
        returncode = 0
        stdout = ""

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = list(cmd)
        return _Proc()

    with patch.object(parallel_runner.subprocess, "run", side_effect=fake_run):
        parallel_runner._run_one(
            case_file=str(case_file),
            case_name="case-a",
            case_payload={"name": "case-a", "steps": []},
            output_dir=tmp_path,
            url="ws://agent",
            internal_url="http://backend",
            history_db=str(history_db),
            base_offset=0,
            clear_history_per_case=True,
            clear_backend_pending_per_case=False,
            clear_backend_planning_intent_per_case=False,
            keep_response_text=False,
            assert_plan_style=False,
            response_timeout=10,
            open_timeout=5,
        )

    cmd = recorded["cmd"]
    assert "--history-db" in cmd
    assert str(history_db) in cmd
