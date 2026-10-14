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


def test_write_rules_lookup_the_rank_before_uttering_one() -> None:
    """用户只给分数没给位次时的规则必须写死（2026-10-07 一分一段工具上线）：

    - 先查 `catalog.get_score_position`（不能自己按分数猜）；
    - 口径是**区间**：同分不可分辨，只能按「位次（一分一段区间，同分不可分辨）」呈现；
    - **测算/默认位次用 `default_rank`**（= lowest_rank，同分最后一名、最保守口径，
      与 hl-wish `scoreToPos` 同口径）：位次缺失时以它作默认位次带上卡
      （`totalScorePos`），并标注是保守推算值；
    - 用户明确给了位次时以用户值为准（**用户 > 表**）；
    - 上游没有该省数据时如实说不可用，**不得估算**。
    """
    rules = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.write.md"
    ).read_text(encoding="utf-8")

    assert "catalog.get_score_position" in rules, "位次工具没有出现在补录规则里"
    assert "一分一段" in rules
    assert "同分不可分辨" in rules, "区间口径没有写进规则"
    assert "default_rank" in rules, "单一默认位次字段没有写进规则"
    assert "最保守" in rules, "default_rank 的口径（最保守/同分最后一名）没有写进规则"
    assert "totalScorePos" in rules, "默认位次与卡片字段的衔接没有写进规则"
    assert "保守值" in rules, "保守推算值的标注要求没有写进规则"
    assert "用户 > 表" in rules, "用户位次优先于表值这条没有写进规则"
    assert "不得估算" in rules
    # 空档案出卡的 110 前置条件也要写死（2026-10-07 真栈实测：只给总分/位次就出卡，
    # 后端 110「请填写各科成绩后再创建会话」直接拒，回合以失败收场）。
    # 协调方口径（2026-10-07）：**空档案首次补录五项集齐才出卡**
    # （省份/科类/批次/各科成绩（完整）/总分），缺任何一项先澄清（一次把缺的都问上）；
    # **已有档案的修改**才允许只带用户说过的字段（增量合并）。
    assert "请填写各科成绩后再创建会话" in rules, "110 拒卡那条没有写进规则"
    assert "五项集齐才出卡" in rules, "空档案五项齐套的要求没有写进规则"
    assert "一次把缺的都问上" in rules, "缺项时一次问全的动作没有写进规则"
    assert "增量合并" in rules, "已有档案增量合并的例外没有写进规则"


def test_write_rules_reuse_code_table_lookups() -> None:
    """编码表查询结果要复用（2026-10-07 真栈实测：同一轮里批次/科目编码反复查）。

    用户侧表现是"正在读取批次编码"刷屏，token 也白烧。规则把复用写死：
    同一轮里批次/科目编码**查一次就够**，拿到结果后不要重复调用。
    """
    rules = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.write.md"
    ).read_text(encoding="utf-8")

    assert "查一次就够" in rules, "编码表复用（查一次就够）没有写进规则"
    assert "不要重复调用" in rules, "禁止重复调用的措辞没有写进规则"
    assert "正在读取批次编码" in rules


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


def test_advancement_is_host_style_and_major_direction_is_recommended_first() -> None:
    """2026-10-09 用户口径：推进靠主持（宣布下一步+直接开始），不用开放式反问；
    专业方向**先推荐、再征询**；能推断的不问；面向用户不甩原始系数/打分。

    这些规则不写进指令/技能文本，模型就会退回「你有什么想法 / 你想学什么」式反问，
    或把 rank 侧打分（`score` 与各维度指数）直接念给用户——两件事在日志上都像"模型不会聊"。
    """
    dev = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.md"
    ).read_text(encoding="utf-8")
    assert "主持者" in dev, "主持者原则没有写进实例级指令"
    assert "能推断的信息不问" in dev, "推断优先没有写进实例级指令"
    assert "先主动推荐" in dev and "你想学哪个方向" in dev, "专业方向'先推荐再征询'没有写进实例级指令"
    assert "不要直接甩原始数值" in dev, "原始数值禁用没有写进实例级指令"
    assert "不要这样做" in dev and "抛回用户" in dev, "反例（清单+抛回用户）没有写进实例级指令"

    base = (
        Path(__file__).parents[2] / "skills" / "codex" / "base_instructions.md"
    ).read_text(encoding="utf-8")
    assert "\n11. " in base, "常驻规则里没有第 11 条（面向用户禁甩原始数值）"
    assert "raw internal numbers" in base
    assert "subject fit" in base

    guide = (
        _root() / "profile-discovery" / "references" / "planner-questioning-guide.md"
    ).read_text(encoding="utf-8")
    assert "Recommend before you ask" in guide, "提问指南没有'先推荐再征询'"
    assert "subjectScoreList" in guide, "提问指南没有'能推断的不问'（优势科目）"
    assert "closed-ended" in guide, "提问指南没有封闭式优先"

    skill = (_root() / "profile-discovery" / "SKILL.md").read_text(encoding="utf-8")
    assert "再询问专业方向" not in skill, "专业方向仍是反问式（旧口径残留）"
    assert "专业方向先推荐、再征询" in skill

    recommendation = (_root() / "candidate-recommendation" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "不直出原始数值" in recommendation, "候选推荐没有'不直出原始数值'"

    write_rules = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.write.md"
    ).read_text(encoding="utf-8")
    assert "先推荐、再征询" in write_rules, "写实例规则没有'专业方向先推荐再征询'"
    assert "内部依据" in write_rules, "写实例规则没有把打分标注为内部依据"


def test_priority_rules_need_a_hit_check_and_budget_intents_are_translated() -> None:
    """2026-10-13 实测（会话 10041981）："学费≤2 万"被表达成优先规则 → 用户确认后
    `409 priority_target_not_in_plan`（方案内零命中）——preview=ready 也挡不住，
    因为 `prioritize_within_tier` 只能重排**方案内已有条目**。两条指令是预防：
    ① 提议优先类规则前先自检方案内命中目标数 ≥1，命中 0 不把提案发出去；
    ② 学费/预算类自然表达由**系统**翻译成正确操作（筛选/替换/补档），
       翻译职责不得推给用户（用户点名：不许要求用户改用程序化措辞）。
    指令文本不写进实例级指令，模型下一次还会把预算塞进 priorityRules。
    """
    dev = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.md"
    ).read_text(encoding="utf-8")
    assert "命中目标数 ≥1" in dev, "优先规则前的命中数自检没有写进实例级指令"
    assert "priority_target_not_in_plan" in dev, "没有点名确认后 409 的后果"
    assert "命中为 0" in dev and "不要把该提案发出去" in dev, "命中 0 的处理没有写进指令"
    assert "翻译职责在系统侧" in dev, "学费/预算类诉求的翻译职责没有写进指令"
    assert "不要要求用户改用" in dev, "没有禁止把翻译责任推回用户"
    assert "替换/补档" in dev, "没有给出预算类诉求的正确动作映射"
    assert "业务语言 + 封闭式" in dev, "拿不准时的确认口径没有写进指令"
    assert "不得把还没进方案的候选说成已经安排" in dev, "文案预支未生效操作的禁令缺失"


def test_career_v1_is_pinned_in_profile_discovery_and_exploration_skills() -> None:
    """career v1（2026-10-14）：发展方向走**四类中文规范标签**的弱偏好语义。

    这组契约分散在四处（收集/探索/推荐/方案），任何一处被改回旧口径
    （英文槽位、硬筛、或重新引用已删除的 career_path_chat），
    用户侧表现都是"方向被当成硬条件筛掉候选"或"方向确认卡出不来了"。
    """
    profile = (_root() / "profile-discovery" / "SKILL.md").read_text(encoding="utf-8")
    assert "careerUpdateRequest" in profile, "画像收集没有结构化草稿字段名"
    for label in ("体制内/考公导向", "稳定就业导向", "深造发展导向", "市场化就业导向"):
        assert label in profile, f"画像收集缺四类规范标签：{label}"
    assert "封闭式四选" in profile, "发展方向没有封闭式四选口径"
    assert "能推断的一律推断" in profile, "发展方向缺'能推断不问'"
    assert "更新发展方向" in profile, "确认卡名称没有写进收集口径"

    exploration = (_root() / "school-major-exploration" / "SKILL.md").read_text(encoding="utf-8")
    assert "职业路径主题" in exploration
    assert "career_path_chat" not in exploration, "探索技能仍引用已删除的 career_path_chat"
    assert "先看学生本人" in exploration
    assert "中低分段" in exploration and "优先就业" in exploration
    assert "弱偏好" in exploration and "不硬筛" in exploration
    assert "preferences.careerTypes" in exploration, "探索技能没有指向快照字段"
    assert "careerUpdateRequest" in exploration, "探索技能没有写方向草稿的触发条件"
    assert "不和意向混用" in exploration


def test_career_v1_weak_preference_is_pinned_in_recommendation_and_plan_skills() -> None:
    recommendation = (_root() / "candidate-recommendation" / "SKILL.md").read_text(encoding="utf-8")
    assert "preferences.careerTypes" in recommendation
    assert "弱偏好" in recommendation
    assert "不做硬筛" in recommendation, "候选推荐仍可能把方向当硬筛"
    assert "Preference Fit" in recommendation

    for name in ("plan-construction", "plan-final-review"):
        body = (_root() / name / "SKILL.md").read_text(encoding="utf-8")
        assert "方向覆盖核对" in body, f"{name} 缺方向覆盖核对"
        assert "preferences.careerTypes" in body, f"{name} 没有指向快照字段"
        assert "承接证据" in body, f"{name} 没有要求逐条给出承接证据"
    review = (_root() / "plan-final-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "不做硬筛" in review and "只审不筛" in review


def test_write_rules_pin_career_update_request_contract() -> None:
    """写实例规则必须把 careerUpdateRequest 的契约写死（career v1）：

    - 字段名与走同一条确认链；
    - `careerTypes` 只能是四类中文规范标签（别名归一在系统侧）；
    - 弱偏好语义（不得据此硬筛），且与提案/补录同属'一回合只出一件事'。
    """
    rules = (
        Path(__file__).parents[2] / "skills" / "codex" / "developer_instructions.write.md"
    ).read_text(encoding="utf-8")
    assert "careerUpdateRequest" in rules
    assert "更新发展方向" in rules
    for label in ("体制内/考公导向", "稳定就业导向", "深造发展导向", "市场化就业导向"):
        assert label in rules, f"写实例规则缺四类规范标签：{label}"
    assert "只能是四类中文规范标签" in rules
    assert "弱偏好" in rules
    assert "更新发展方向" in rules
    assert "一回合" in rules and "只出一件事" in rules
