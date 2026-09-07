from __future__ import annotations

import json
from pathlib import Path


SKILL_NAMES = {
    "profile-discovery",
    "school-major-exploration",
    "admission-fact-analysis",
    "candidate-recommendation",
    "plan-construction",
    "plan-final-review",
}
REQUIRED_SECTIONS = (
    "## 适用条件",
    "## 不适用条件",
    "## 前置状态",
    "## 允许能力",
    "## 标准步骤",
    "## Evidence 要求",
    "## 单轮调用预算",
    "## 停止条件",
    "## 输出结构",
    "## 降级策略",
)


def _root() -> Path:
    return Path(__file__).parents[2] / "skills" / "codex"


def _frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, raw, body = text.split("---\n", 2)
    values: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip().strip('"')
    return values, body


def test_codex_skill_manifest_is_complete() -> None:
    root = _root()
    names = {path.parent.name for path in root.glob("*/SKILL.md")}
    assert names == SKILL_NAMES


def test_each_skill_has_frontmatter_and_required_operating_sections() -> None:
    root = _root()
    for name in sorted(SKILL_NAMES):
        frontmatter, body = _frontmatter(root / name / "SKILL.md")
        assert frontmatter["name"] == name
        assert frontmatter["description"].startswith("Use when")
        assert frontmatter["version"]
        for section in REQUIRED_SECTIONS:
            assert section in body, f"{name} missing {section}"


def test_base_rules_and_high_risk_skill_guards_are_explicit() -> None:
    root = _root()
    base = (root / "base_instructions.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "authoritative facts",
        "do not guess",
        "entity ambiguity",
        "evidence",
        "proposal",
        "snapshot",
    ):
        assert phrase in base

    candidate = (root / "candidate-recommendation" / "SKILL.md").read_text(encoding="utf-8").lower()
    for phrase in ("province", "year", "rank", "score", "hard constraint", "clarif"):
        assert phrase in candidate

    for name in ("plan-construction", "plan-final-review"):
        body = (root / name / "SKILL.md").read_text(encoding="utf-8").lower()
        assert "read-only" in body
        assert "proposal" in body
        assert "must not" in body or "forbidden" in body


def test_risk_bands_and_reference_documents_are_present() -> None:
    root = _root()
    recommendation = (root / "candidate-recommendation" / "SKILL.md").read_text(encoding="utf-8")
    for phrase in ("<50%", "50%~70%", "70%~99%", "冲", "稳", "保"):
        assert phrase in recommendation
    for name in (
        "evidence-policy.md",
        "planner-questioning-guide.md",
        "recommendation-explanation-guide.md",
    ):
        path = root / "references" / name
        assert path.exists()
        assert path.read_text(encoding="utf-8").strip()


def test_codex_plugin_manifest_points_to_all_skills() -> None:
    manifest = json.loads((_root() / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "zhiyuan-codex-planner"
    assert manifest["version"]
    assert set(manifest["skills"]) == SKILL_NAMES
