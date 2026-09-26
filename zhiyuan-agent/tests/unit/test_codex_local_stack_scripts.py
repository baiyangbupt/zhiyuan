from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT_DIR = Path(__file__).resolve().parents[3]
PREFLIGHT = ROOT_DIR / "scripts" / "preflight-codex-local.sh"
START = ROOT_DIR / "scripts" / "start-codex-local.sh"
STOP = ROOT_DIR / "scripts" / "stop-codex-local.sh"
SMOKE_PUBLIC = ROOT_DIR / "scripts" / "smoke-codex-public.sh"


def _run(script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env.update(env or {})
    for name in (
        "CODEX_LOCAL_SERVER_CONFIG",
        "CODEX_LOCAL_DATASET",
        "CODEX_LOCAL_CODEX_HOME",
        "CODEX_LOCAL_RUN_DIR",
    ):
        if not (env or {}).get(name):
            process_env.pop(name, None)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=ROOT_DIR,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_local_stack_scripts_have_valid_bash_syntax() -> None:
    for script in (PREFLIGHT, START, STOP):
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_start_refuses_to_build_or_launch_without_private_server_config() -> None:
    result = _run(START, "--skip-web")

    assert result.returncode != 0
    assert "CODEX_LOCAL_SERVER_CONFIG" in result.stderr
    assert "building backend jar" not in result.stdout


def test_preflight_rejects_a_checked_in_server_config_before_using_it(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    result = _run(
        PREFLIGHT,
        "--skip-web",
        "--skip-build",
        env={
            "CODEX_LOCAL_SERVER_CONFIG": str(ROOT_DIR / "zhiyuan-server/src/main/resources/application-local.yml"),
            "CODEX_LOCAL_DATASET": "private-resettable",
            "CODEX_LOCAL_CODEX_HOME": str(codex_home),
        },
    )

    assert result.returncode != 0
    assert "must not use zhiyuan-server/src/main/resources defaults" in result.stderr


def test_preflight_requires_an_explicit_isolated_data_source(tmp_path: Path) -> None:
    config = tmp_path / "application-codex-local.yml"
    config.write_text("server:\n  port: 18290\n", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    result = _run(
        PREFLIGHT,
        "--skip-web",
        "--skip-build",
        env={
            "CODEX_LOCAL_SERVER_CONFIG": str(config),
            "CODEX_LOCAL_CODEX_HOME": str(codex_home),
        },
    )

    assert result.returncode != 0
    assert "private-resettable" in result.stderr


def test_stop_refuses_to_target_an_arbitrary_directory(tmp_path: Path) -> None:
    result = _run(STOP, str(tmp_path))

    assert result.returncode != 0
    assert "run directory must be a direct child" in result.stderr


def test_preflight_rejects_a_run_directory_with_path_traversal(tmp_path: Path) -> None:
    config = tmp_path / "application-codex-local.yml"
    config.write_text("server:\n  port: 18290\n", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    escaped_run_dir = ROOT_DIR / ".runtime" / "codex-local-run" / ".." / "outside-run"

    result = _run(
        PREFLIGHT,
        "--skip-web",
        "--skip-build",
        "--run-dir",
        str(escaped_run_dir),
        env={
            "CODEX_LOCAL_SERVER_CONFIG": str(config),
            "CODEX_LOCAL_DATASET": "private-resettable",
            "CODEX_LOCAL_CODEX_HOME": str(codex_home),
        },
    )

    assert result.returncode != 0
    assert "run directory must be a direct child" in result.stderr


def _access_env(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """`--print-access-env`：把脚本**实际会用的**访问面变量打出来（不启动任何服务 ✓）。

    没有这个出口就只能断言源码文本 ✗——那测不出"值到底落实成了什么" ✗
    （任务书 Task C2 原话："脚本将值落实到实际使用的 NEXT_PUBLIC 变量及 Agent Origin allowlist"）。
    """
    return _run(START, "--print-access-env", *args, env=env)


def test_public_smoke_script_rejects_bad_origin_before_any_request() -> None:
    """冒烟脚本的守卫：**没给 origin / 不是 https / 带路径**都要在发请求前就拒 ✓
    （否则会对着错的地址跑一轮，还把它当成"失败"记下来 ✗）。"""
    for args, needle in (
        ([], "--origin is required"),
        (["--origin", "http://insecure.example"], "must be https"),
        (["--origin", "https://h.example/path"], "must not carry a path"),
        (["--origin", "https://h.example", "--unknown"], "unknown option"),
    ):
        result = _run(SMOKE_PUBLIC, *args)
        assert result.returncode != 0, args
        assert needle in result.stderr, (args, result.stderr)


def test_local_mode_keeps_loopback_ws_override() -> None:
    result = _access_env(env={"CODEX_LOCAL_ACCESS_MODE": "local"})

    assert result.returncode == 0, result.stderr
    assert 'NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE="ws://127.0.0.1:18291"' in result.stdout


def test_public_test_mode_clears_ws_override_and_requires_explicit_test_outer() -> None:
    """公开模式：**清空 WS override** ✓（同源由 `window.location` 派生 ✓）+
    outer 必须是**显式配置的受控测试源** ✓（不许留 production 默认 ✗）。"""
    result = _access_env(env={
        "CODEX_LOCAL_ACCESS_MODE": "public-test",
        "CODEX_LOCAL_PUBLIC_ORIGIN": "https://test-wwww.gaotuzhiyuan.com",
        "CODEX_LOCAL_OUTER_API_BASE_URL": "https://test-api.gaotuzhiyuan.com",
    })

    assert result.returncode == 0, result.stderr
    assert "NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=\"\"" in result.stdout
    assert "NEXT_PUBLIC_OUTER_API_BASE_URL=https://test-api.gaotuzhiyuan.com" in result.stdout


def test_public_test_rejects_origin_with_path_or_credentials() -> None:
    for bad in (
        "https://test-wwww.gaotuzhiyuan.com/console",
        "https://user:pass@test-wwww.gaotuzhiyuan.com",
    ):
        result = _access_env(env={
            "CODEX_LOCAL_ACCESS_MODE": "public-test",
            "CODEX_LOCAL_PUBLIC_ORIGIN": bad,
            "CODEX_LOCAL_OUTER_API_BASE_URL": "https://test-api.gaotuzhiyuan.com",
        })

        assert result.returncode != 0, f"{bad} 应被拒"
        assert "public origin" in result.stderr.lower()


def test_public_test_rejects_outer_that_is_self_or_default_production() -> None:
    """outer 指向**自己**（同源）或在没显式配置时回落到**默认生产域名** ✗ 都要拒。"""
    base = {
        "CODEX_LOCAL_ACCESS_MODE": "public-test",
        "CODEX_LOCAL_PUBLIC_ORIGIN": "https://test-wwww.gaotuzhiyuan.com",
    }
    same_origin = _access_env(env={**base, "CODEX_LOCAL_OUTER_API_BASE_URL": "https://test-wwww.gaotuzhiyuan.com"})
    assert same_origin.returncode != 0, "outer 指向自己应被拒"
    assert "outer" in same_origin.stderr.lower()

    unset = _access_env(env=base)
    assert unset.returncode != 0, "公开模式必须显式给 outer，不许回落到生产默认"
    assert "outer" in unset.stderr.lower()


def test_web_launch_consumes_the_resolved_access_values() -> None:
    """**声明了但没人消费** ✗ 是这类改动最容易留下的坑 ✓（任务书原话：
    "不只声明一个未消费的 PUBLIC_TEST_ORIGIN" ✗）。所以这里盯**接线**：
    解析出的值必须真的进 Web 的环境 ✓，而两处硬设必须消失 ✗。"""
    source = START.read_text(encoding="utf-8")

    assert '"NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=$ACCESS_WS_OVERRIDE"' in source
    assert '"NEXT_PUBLIC_OUTER_API_BASE_URL=$ACCESS_OUTER_API_BASE_URL"' in source
    assert "NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=ws://127.0.0.1:" not in source, "硬设 loopback 必须消失"
    assert "NEXT_PUBLIC_OUTER_API_BASE_URL=https://www.gaotuzhiyuan.com" not in source, "硬设生产 outer 必须消失"


def test_lifecycle_scripts_require_a_per_run_process_marker() -> None:
    start_source = START.read_text(encoding="utf-8")
    stop_source = STOP.read_text(encoding="utf-8")

    assert 'exec env "CODEX_LOCAL_RUN_DIR=$RUN_DIR" setsid "$@"' in start_source
    assert "environment_matches_run" in stop_source
    assert 'CODEX_LOCAL_RUN_DIR=$RUN_DIR' in stop_source
