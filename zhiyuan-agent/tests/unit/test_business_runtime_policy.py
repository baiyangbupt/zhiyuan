from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.runtime_policy import DISABLED_FEATURES, validate_effective_policy, verify_binary
from app.mcp_server.skill_resources import PREFIX, list_skills, read_skill


def effective():
    return {"config": {"features": dict.fromkeys(DISABLED_FEATURES, False),
                       "web_search": "disabled", "mcp_servers": {"zhiyuan_domain": {}}}}


def test_effective_policy_rejects_inherited_tools():
    validate_effective_policy(effective())
    for name in DISABLED_FEATURES:
        payload = effective()
        payload["config"]["features"][name] = True
        with pytest.raises(RuntimeError, match="policy"):
            validate_effective_policy(payload)
    payload = effective()
    payload["config"]["mcp_servers"]["personal_server"] = {}
    with pytest.raises(RuntimeError, match="Unexpected"):
        validate_effective_policy(payload)
    payload["config"]["mcp_servers"]["personal_server"]["enabled"] = False
    validate_effective_policy(payload)


@pytest.mark.parametrize("payload", [{}, {"config": {}}, {"config": {"web_search": "live"}}])
def test_missing_effective_policy_fails_closed(payload):
    with pytest.raises(RuntimeError):
        validate_effective_policy(payload)


async def test_binary_version_guard_checks_real_process(tmp_path):
    import sys
    script = tmp_path / "codex"
    script.write_text(f"#!{sys.executable}\nprint('codex-cli 0.165.0')\n")
    script.chmod(0o700)
    await verify_binary(SimpleNamespace(bin=str(script), expected_version="0.165.0"))
    with pytest.raises(RuntimeError, match="version mismatch"):
        await verify_binary(SimpleNamespace(bin=str(script), expected_version="0.156.1"))


def test_skill_resources_preserve_body_and_references_but_deny_paths(tmp_path):
    skill = tmp_path / "planner-routing"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("routing rules")
    (skill / "references/evidence.md").write_text("evidence rules")
    outside = tmp_path.parent / "outside-secret.md"
    outside.write_text("private")
    (skill / "references/leak.md").symlink_to(outside)
    uris = {r["uri"] for r in list_skills(tmp_path)}
    assert uris == {PREFIX + "planner-routing/SKILL.md", PREFIX + "planner-routing/references/evidence.md"}
    assert read_skill(PREFIX + "planner-routing/SKILL.md", tmp_path)["contents"][0]["text"] == "routing rules"
    for uri in ("file:///etc/passwd", PREFIX + "../outside-secret.md", PREFIX + "planner-routing/references/leak.md"):
        with pytest.raises(ValueError, match="unknown"):
            read_skill(uri, tmp_path)


def test_packaged_routing_skill_is_available_without_shell():
    assert "planner-routing" in read_skill(PREFIX + "planner-routing/SKILL.md")["contents"][0]["text"]


def test_command_overrides_user_tool_defaults():
    from app.config import CodexAppServerConfig
    from app.gateway.composition import build_codex_command
    command = build_codex_command("codex_write", CodexAppServerConfig(_env_file=None, binding_registry_path="/tmp/b.sqlite"))
    assert 'web_search="disabled"' in command
    for name in DISABLED_FEATURES:
        assert f"features.{name}=false" in command


def test_packaged_cross_skill_references_are_all_readable_mcp_resources():
    import re
    from app.mcp_server.skill_resources import skill_files, skill_instructions

    checked = 0
    for uri in skill_files():
        body = read_skill(uri)["contents"][0]["text"]
        for relative in re.findall(r"r1/([\w./-]+\.md)", body):
            assert read_skill(PREFIX + relative)["contents"][0]["text"]
            checked += 1
    assert checked > 0
    instructions = skill_instructions()
    assert "r1/" in instructions and "do not consume" in instructions
