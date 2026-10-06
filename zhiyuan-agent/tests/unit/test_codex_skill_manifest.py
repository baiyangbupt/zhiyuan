from __future__ import annotations

import json
import re
from pathlib import Path


SKILL_NAMES = {
    # 入口技能：只选路不回答（对应 superpowers 的 using-superpowers）。
    # 2026-09-21 加：此前没有任何"该走哪个技能"的路由，模型面对
    # "计算机和物理哪个好"只能自己猜，猜成了"要参数"。
    "planner-routing",
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


PLUGIN_ROOT = (
    Path(__file__).parents[2]
    / "skills"
    / "codex-marketplace"
    / "plugins"
    / "zhiyuan-codex-planner"
)


def _root() -> Path:
    """技能真身所在目录。

    2026-09-21 从 `skills/codex/` 搬到这里：`skills/codex/plugin.json` 是个**手写的
    自定义清单**，而 codex 只认插件布局（`.codex-plugin/plugin.json` +
    marketplace 注册）。实测后果是**模型一份技能都看不到**——`<skills_instructions>`
    里只有系统技能，于是"计算机和物理哪个好"这类问题只能退回"要参数"。
    布局按设计书 §7.3 恢复。指令文件（base/developer）仍留在 `skills/codex/`。
    """
    return PLUGIN_ROOT / "skills"


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
    base = (
        Path(__file__).parents[2] / "skills" / "codex" / "base_instructions.md"
    ).read_text(encoding="utf-8").lower()
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
    # 参考文档放在**各自归属技能的 references/ 下**（codex 要求 skills/ 下每个
    # 子目录都得是技能，所以不能有个共享的 references/ 目录）。
    for owner, name in (
        ("admission-fact-analysis", "evidence-policy.md"),
        ("profile-discovery", "planner-questioning-guide.md"),
        ("candidate-recommendation", "recommendation-explanation-guide.md"),
    ):
        path = _root() / owner / "references" / name
        assert path.exists()
        assert path.read_text(encoding="utf-8").strip()


def test_every_skill_that_needs_a_reference_points_at_a_real_path() -> None:
    """引用必须是能寻址的路径，而且文件真的在。

    "写了文档没人读"是这条线反复出现的失败方式（三份 reference 从没被任何技能引用过）。
    所以这里既测"有没有引用"，也测"引用的文件存不存在"——只测前者的话，
    一个指向不存在文件的引用同样能让测试全绿。
    """
    for skill in sorted(SKILL_NAMES):
        body = (_root() / skill / "SKILL.md").read_text(encoding="utf-8")
        for target in re.findall(r"`r1/([^`]+?\.md)`", body):
            assert (_root() / target).exists(), f"{skill} 引用了不存在的 {target}"


def test_codex_plugin_manifest_is_a_real_codex_plugin() -> None:
    """清单必须是 codex 认的那一种。

    这里曾经钉的是**手写清单**的形状（`skills` 是一个名字列表）——它通过了测试，
    却从来不被 codex 读取：模型一份业务技能都看不到。测"文件里写了什么"是不够的，
    要测"消费方认不认这个形状"：`.codex-plugin/plugin.json` + `skills` 指向目录。
    """
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "zhiyuan-codex-planner"
    assert manifest["version"]
    assert manifest["skills"] == "./skills/"
    assert manifest["interface"]["displayName"]

    # 指向的目录里正好是这几个技能，不多不少。
    listed = {path.parent.name for path in (_root()).glob("*/SKILL.md")}
    assert listed == SKILL_NAMES


def test_the_marketplace_lists_this_plugin() -> None:
    """marketplace 清单也必须存在且指向本插件——没有它，插件装不上，
    技能照样到不了模型眼前。"""
    marketplace = json.loads(
        (
            Path(__file__).parents[2]
            / "skills"
            / "codex-marketplace"
            / ".agents"
            / "plugins"
            / "marketplace.json"
        ).read_text(encoding="utf-8")
    )
    assert marketplace["name"] == "zhiyuan-local"
    entries = {item["name"]: item for item in marketplace["plugins"]}
    assert "zhiyuan-codex-planner" in entries
    assert entries["zhiyuan-codex-planner"]["source"]["path"] == "./plugins/zhiyuan-codex-planner"


def test_write_rules_require_looking_up_codes_before_the_card() -> None:
    """写实例的补录规则必须写死"先查编码、再出卡"（2026-10-06 真事故）：

    模型把各科出成 `[{"score": 88}, …]`（没有科目编码），合并后 `subject=null`
    一路炸到下游；批次同理（名字不是编码）。修复的**入口那一半**就是把两张编码表
    变成规则里的前置动作——规则不写，模型照样只报分数。
    """
    rules = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.write.md"
    ).read_text(encoding="utf-8")

    assert "catalog.get_subject_options" in rules, "科目编码表没有出现在补录规则里"
    assert "catalog.get_batch_options" in rules, "批次编码表没有出现在补录规则里"
    assert "先查编码" in rules and "没有编码就没有卡" in rules
    # 拒绝原因（非标准选科编码）也要写在规则里：模型知道自己会被什么挡下。
    assert "非标准选科编码" in rules
