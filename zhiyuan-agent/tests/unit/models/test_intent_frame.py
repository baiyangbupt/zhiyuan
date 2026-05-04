"""IntentFrame 模型单元测试。"""

import pytest
from pydantic import ValidationError

from app.models.intent_frame import (
    IntentFrame,
    ScopeSpec,
    TargetSpec,
)


# ---------------------------------------------------------------------------
# TargetSpec
# ---------------------------------------------------------------------------

class TestTargetSpec:
    """TargetSpec 基本行为。"""

    def test_defaults(self):
        t = TargetSpec()
        assert t.volunteer_refs == []
        assert t.school_names == []
        assert t.major_names == []
        assert t.region_names == []
        assert t.career_types == []
        assert t.review_issue_code is None
        assert t.position is None

    def test_has_refs_false_when_empty(self):
        assert not TargetSpec().has_refs

    @pytest.mark.parametrize("field,value", [
        ("volunteer_refs", ["@3"]),
        ("school_names", ["北京大学"]),
        ("major_names", ["计算机科学与技术"]),
        ("region_names", ["北京"]),
    ])
    def test_has_refs_true(self, field, value):
        t = TargetSpec(**{field: value})
        assert t.has_refs

    def test_career_types_not_affect_has_refs(self):
        """career_types 不影响 has_refs（设计如此，career 不是具体引用）。"""
        t = TargetSpec(career_types=["体制内"])
        assert not t.has_refs

    def test_review_issue_code_not_affect_has_refs(self):
        """review_issue_code 不影响 has_refs。"""
        t = TargetSpec(review_issue_code="high_tuition")
        assert not t.has_refs

    def test_full_construction(self):
        t = TargetSpec(
            volunteer_refs=["@1", "@2"],
            school_names=["清华大学"],
            major_names=["电子信息"],
            region_names=["上海"],
            career_types=["金融"],
            review_issue_code="cooperative_program",
            position=5,
        )
        assert t.has_refs
        assert t.position == 5
        assert t.review_issue_code == "cooperative_program"


# ---------------------------------------------------------------------------
# ScopeSpec
# ---------------------------------------------------------------------------

class TestScopeSpec:
    """ScopeSpec 基本行为。"""

    def test_defaults(self):
        s = ScopeSpec()
        assert s.tier == ""
        assert s.province == ""
        assert s.school_tags == []
        assert s.major_tags == []
        assert s.school_keyword == ""
        assert s.major_keyword == ""
        assert s.limit == 5
        assert s.is_review_issue_batch is False

    def test_has_filters_false_when_empty(self):
        assert not ScopeSpec().has_filters

    @pytest.mark.parametrize("field,value", [
        ("tier", "冲"),
        ("tier", "稳"),
        ("tier", "保"),
        ("province", "北京"),
        ("school_tags", ["985"]),
        ("major_tags", ["工学"]),
        ("school_keyword", "工业"),
        ("major_keyword", "计算机"),
    ])
    def test_has_filters_true(self, field, value):
        s = ScopeSpec(**{field: value})
        assert s.has_filters

    def test_limit_and_batch_not_affect_has_filters(self):
        """limit 和 is_review_issue_batch 不影响 has_filters。"""
        s = ScopeSpec(limit=10, is_review_issue_batch=True)
        assert not s.has_filters

    def test_tier_validation(self):
        """tier 必须是合法枚举值。"""
        with pytest.raises(ValidationError):
            ScopeSpec(tier="超")


# ---------------------------------------------------------------------------
# IntentFrame
# ---------------------------------------------------------------------------

class TestIntentFrame:
    """IntentFrame 构造与序列化。"""

    def test_minimal_construction(self):
        frame = IntentFrame(task_layer="plan", verb="query")
        assert frame.task_layer == "plan"
        assert frame.verb == "query"
        assert frame.topic == "general"
        assert not frame.is_confirmation_of_previous
        assert frame.raw_utterance == ""

    def test_full_construction(self):
        frame = IntentFrame(
            task_layer="plan",
            topic="school",
            verb="add",
            target=TargetSpec(volunteer_refs=["@1"]),
            scope=ScopeSpec(province="北京", tier="冲"),
            raw_utterance="帮我加一个北京的冲刺学校",
            is_confirmation_of_previous=False,
        )
        assert frame.target.has_refs
        assert frame.scope.has_filters
        assert frame.raw_utterance == "帮我加一个北京的冲刺学校"

    @pytest.mark.parametrize("task_layer", ["explore", "intent", "plan"])
    def test_valid_task_layers(self, task_layer):
        frame = IntentFrame(task_layer=task_layer, verb="query")
        assert frame.task_layer == task_layer

    def test_invalid_task_layer(self):
        with pytest.raises(ValidationError):
            IntentFrame(task_layer="invalid", verb="query")

    @pytest.mark.parametrize("topic", [
        "career", "school", "major", "region", "plan", "general",
    ])
    def test_valid_topics(self, topic):
        frame = IntentFrame(task_layer="explore", verb="query", topic=topic)
        assert frame.topic == topic

    def test_invalid_topic(self):
        with pytest.raises(ValidationError):
            IntentFrame(task_layer="explore", verb="query", topic="invalid")

    @pytest.mark.parametrize("verb", [
        # Plan 操作
        "query", "analyze", "review", "generate",
        "add", "remove", "move", "pin", "unpin",
        "replace", "reorder", "compensate",
        # Explore 操作
        "compare", "recommend", "explain", "explore",
        # Intent 操作
        "set_preference", "set_constraint", "remove_preference",
        # 确认/拒绝
        "confirm", "reject",
    ])
    def test_valid_verbs(self, verb):
        frame = IntentFrame(task_layer="plan", verb=verb)
        assert frame.verb == verb

    def test_invalid_verb(self):
        with pytest.raises(ValidationError):
            IntentFrame(task_layer="plan", verb="invalid_verb")

    def test_confirm_intent(self):
        """确认意图：is_confirmation_of_previous=True。"""
        frame = IntentFrame(
            task_layer="plan",
            verb="confirm",
            is_confirmation_of_previous=True,
        )
        assert frame.is_confirmation_of_previous
        assert frame.verb == "confirm"

    def test_reject_intent(self):
        frame = IntentFrame(
            task_layer="plan",
            verb="reject",
            is_confirmation_of_previous=True,
        )
        assert frame.verb == "reject"
        assert frame.is_confirmation_of_previous

    def test_serialization_roundtrip(self):
        """序列化/反序列化完整往返。"""
        frame = IntentFrame(
            task_layer="intent",
            topic="major",
            verb="set_preference",
            target=TargetSpec(major_names=["计算机", "软件工程"]),
            scope=ScopeSpec(major_tags=["工学"]),
            raw_utterance="我比较喜欢计算机和软件工程",
        )
        data = frame.model_dump()
        restored = IntentFrame.model_validate(data)
        assert restored == frame

    def test_json_roundtrip(self):
        """JSON 序列化/反序列化。"""
        frame = IntentFrame(
            task_layer="plan",
            verb="remove",
            target=TargetSpec(
                volunteer_refs=["@5"],
                review_issue_code="high_tuition",
            ),
        )
        json_str = frame.model_dump_json()
        restored = IntentFrame.model_validate_json(json_str)
        assert restored.target.review_issue_code == "high_tuition"
        assert restored.target.volunteer_refs == ["@5"]

    def test_explore_career_intent(self):
        """Explore 职业方向意图。"""
        frame = IntentFrame(
            task_layer="explore",
            topic="career",
            verb="explore",
            target=TargetSpec(career_types=["体制内"]),
            raw_utterance="体制内适不适合我",
        )
        assert frame.task_layer == "explore"
        assert frame.target.career_types == ["体制内"]

    def test_intent_set_constraint(self):
        """Intent 约束设置。"""
        frame = IntentFrame(
            task_layer="intent",
            verb="set_constraint",
            target=TargetSpec(region_names=["上海"]),
            raw_utterance="不想去上海",
        )
        assert frame.task_layer == "intent"
        assert frame.verb == "set_constraint"
