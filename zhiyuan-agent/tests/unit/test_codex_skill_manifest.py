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


def test_base_rules_require_escaping_ascii_quotes_inside_json_string_values() -> None:
    """字符串值里的英文双引号必须转义（2026-10-06 真事故，session 10041948）。

    模型在 `message` 里写了 `有的省是"第一段/第二段"，有的是"本科批/专科批"`——
    未转义的 `"` 让 `json.loads` 在 `Expecting ',' delimiter` 上失败 → harness 抽不出
    结构化输出 → 修复回合也救不回来 → 用户看到"当前对话引擎暂时不可用"。
    解析层的窄口径救回（`app/harness/codex.py`）与修复回合带原文是另外两道闸；
    这一条是**最前面那道**——规则不写，模型照样从源头写坏。

    分层口径（2026-10-06 真栈复现后放宽，协调方拍板）：绝对禁令会让模型连
    合法转义（`\\"`）与逐字引用用户原话都拒绝（真栈实测三回合皆拒），
    伤对话质量；改为「」/『』优先 + 确需时按 JSON 转义 + 禁止未转义的裸引号。
    """
    base = (
        Path(__file__).parents[2] / "skills" / "codex" / "base_instructions.md"
    ).read_text(encoding="utf-8")
    lowered = base.lower()

    assert "「」" in base and "『』" in base, "引号替代写法没有出现在基础规则里"
    assert "double quote" in lowered
    assert "string value" in lowered
    assert "json" in lowered
    # 精确锁定分层口径：转义写法（backslash + quote）必须写在规则里（含微型正例），
    # 禁止的是**未转义**的裸引号。
    assert '\\"' in base, "规则里没有给出转义写法（backslash + quote）"
    assert "escape" in lowered or "escaped" in lowered
    assert "unescaped" in lowered


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


def test_base_rules_forbid_internal_vocabulary_in_user_visible_text() -> None:
    """第 10 条：给用户的文本不得出现内部枚举/字段名（2026-10-06 真事故）。

    用户实测回复里出现「规划阶段也从「ordered」推进到「profile_ready」」——
    注入上下文里全是机器码（快照/state_patch/执行计划/工具契约），模型把内部
    状态原样讲给了用户听。规则是**最前面那道闸**（网关侧的内部分隔标签 +
    "只能用业务语言转述"是同时加的另一道，见
    `test_gateway_internal_state_tags.py` / `test_shadow_gateway.py`）。

    这里钉四件事：第 10 条真的在 9 条之后存在、禁用词有清单、正反例都有
    （只写禁令不写"该怎么说"，模型只能自己造句）、写实例规则同步了一段。
    """
    base = (
        Path(__file__).parents[2] / "skills" / "codex" / "base_instructions.md"
    ).read_text(encoding="utf-8")
    assert "\n10. " in base, "现有 9 条之后没有新增第 10 条"
    for banned in (
        "`ordered`",
        "`profile_ready`",
        "`snapshotVersion`",
        "`workspaceVersion`",
        "`planningStage`",
        "`actionStatus`",
        "`responseType`",
        "`artifactRef`",
        "`proposalRef`",
        "`staleFlags`",
    ):
        assert banned in base, f"第 10 条的禁用词清单缺 {banned}"
    # 正反例都要在（反例=用户实测那句原文，正例=业务语言的说法）。
    assert "Bad (never do this)" in base
    assert "Good:" in base
    assert "资料已补齐" in base
    assert "plain business language" in base.lower()

    write_rules = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.write.md"
    ).read_text(encoding="utf-8")
    assert "业务语言" in write_rules, "写实例规则没有同步「给用户的话用业务语言」"
    assert "profile_ready" in write_rules
