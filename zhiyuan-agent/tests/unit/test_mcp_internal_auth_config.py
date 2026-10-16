from __future__ import annotations

import json
import re

import pytest

from app.config import CodexAppServerConfig
from app.gateway.composition import build_codex_command


@pytest.mark.parametrize("mode", ["codex_readonly", "codex_write"])
def test_mcp_inherits_backend_and_token_names_without_command_line_secrets(monkeypatch, mode):
    token = "mcp-offline-test-credential"
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", token)
    config = CodexAppServerConfig(binding_registry_path="/tmp/offline-bindings.json", _env_file=None)
    command = build_codex_command(mode, config)
    settings = command[command.index("--config") + 1]
    inherited = json.loads(re.search(r"env_vars=(\[[^\]]*\])", settings).group(1))
    assert "INTERNAL_SERVICE_TOKEN" in inherited
    assert "INTERNAL_SERVICE_URL" in inherited
    assert "INTERNAL_SERVICE_TIMEOUT_SECONDS" in inherited
    assert "MCP_MODE" in inherited
    assert token not in " ".join(command)
