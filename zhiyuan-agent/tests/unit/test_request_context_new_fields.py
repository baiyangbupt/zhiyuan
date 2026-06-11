"""Tests for RequestContext new fields (chat_history, batch, score_detail, planning_summary)."""

from __future__ import annotations

import pytest

from app.agent.context import PlanningSummary, RequestContext


class TestRequestContextNewFields:
    """Tests for the new fields added to RequestContext."""

    def test_new_fields_default_to_none(self):
        """Test that new fields default to None."""
        ctx = RequestContext(userid="u1", sessionid="s1")

        assert ctx.chat_history is None
        assert ctx.batch is None
        assert ctx.score_detail is None
        assert ctx.planning_summary is None

    def test_set_chat_history(self):
        """Test setting chat_history field."""
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        ctx = RequestContext(userid="u1", sessionid="s1", chat_history=history)

        assert ctx.chat_history == history
        assert len(ctx.chat_history) == 2

    def test_set_batch_bachelor(self):
        """Test setting batch='01' for bachelor."""
        ctx = RequestContext(userid="u1", sessionid="s1", batch="01")

        assert ctx.batch == "01"

    def test_set_batch_associate(self):
        """Test setting batch for associate degree."""
        ctx = RequestContext(userid="u1", sessionid="s1", batch="02")

        assert ctx.batch == "02"

    def test_set_score_detail(self):
        """Test setting score_detail field."""
        score = {"sex": {"name": "男"}, "province": {"name": "北京"}}
        ctx = RequestContext(userid="u1", sessionid="s1", score_detail=score)

        assert ctx.score_detail == score
        assert ctx.score_detail["sex"]["name"] == "男"

    def test_set_planning_summary(self):
        """Test setting planning_summary field."""
        summary = PlanningSummary(
            phase="reviewed",
            version=3,
            candidate_target_total=30,
            draft_total=20,
            draft_target_total=24,
            ordered_total=20,
            ordered_target_total=24,
            review_risk_count=2,
            pending_action_count=1,
        )
        ctx = RequestContext(userid="u1", sessionid="s1", planning_summary=summary)

        assert ctx.planning_summary is summary
        assert ctx.planning_summary.phase == "reviewed"
        assert ctx.planning_summary.review_risk_count == 2
        assert ctx.planning_summary.ordered_target_total == 24

    def test_all_fields_together(self):
        """Test setting all fields together."""
        ctx = RequestContext(
            userid="u1",
            sessionid="s1",
            chat_history=[{"role": "user", "content": "hi"}],
            batch="01",
            score_detail={"sex": {"name": "女"}, "province": {"name": "浙江"}},
        )

        assert ctx.userid == "u1"
        assert ctx.sessionid == "s1"
        assert ctx.chat_history is not None
        assert ctx.batch == "01"
        assert ctx.score_detail is not None

    def test_planning_summary_from_backend_state(self):
        """Test parsing planning summary from backend state payload."""
        raw_state = {
            "phase": "reviewed",
            "version": 5,
            "staleFlags": {"review": False},
            "candidatePoolState": {"requiredCount": 30},
            "draftPlanState": {"summary": {"total": 12, "targetCount": 30}},
            "orderedPlanState": {"summary": {"total": 10, "targetCount": 30}},
            "reviewState": {
                "status": "completed",
                "summary": {"total": 4, "warnCount": 1, "riskCount": 2},
                "checks": [
                    {"passed": False, "summary": "保区占比过低"},
                    {"passed": False, "summary": "本省保底志愿数量不足"},
                    {"passed": True, "summary": "ignored"},
                ],
            },
            "pendingActions": [
                {"summary": "补充保区志愿"},
                {"summary": "补足志愿总数量"},
            ],
        }

        summary = PlanningSummary.from_backend_state(raw_state)

        assert summary is not None
        assert summary.phase == "reviewed"
        assert summary.version == 5
        assert summary.candidate_target_total == 30
        assert summary.draft_total == 12
        assert summary.draft_target_total == 30
        assert summary.ordered_total == 10
        assert summary.ordered_target_total == 30
        assert summary.review_risk_count == 2
        assert summary.pending_action_count == 2
        assert summary.risk_summaries == ["保区占比过低", "本省保底志愿数量不足"]
        assert summary.pending_action_summaries == ["补充保区志愿", "补足志愿总数量"]

    def test_planning_summary_prefers_unit_totals(self):
        """Test preferring unit total counts in majorGroup mode."""
        raw_state = {
            "phase": "ordered",
            "version": 6,
            "candidatePoolState": {"requiredCount": 30},
            "draftPlanState": {"summary": {"unitTotal": 24, "targetUnitCount": 30, "total": 48}},
            "orderedPlanState": {"summary": {"unitTotal": 24, "targetUnitCount": 30, "total": 48}},
            "reviewState": {"summary": {}},
        }

        summary = PlanningSummary.from_backend_state(raw_state)

        assert summary is not None
        assert summary.draft_total == 24
        assert summary.draft_target_total == 30
        assert summary.ordered_total == 24
        assert summary.ordered_target_total == 30

    def test_planning_summary_reads_working_plan_state(self):
        """Test parsing planning summary from the new workingPlanState field."""
        raw_state = {
            "phase": "selected",
            "version": 7,
            "candidatePoolState": {"requiredCount": 45},
            "workingPlanState": {"summary": {"unitTotal": 18, "targetUnitCount": 45, "total": 36}},
            "orderedPlanState": {"summary": {}},
            "reviewState": {"summary": {}},
        }

        summary = PlanningSummary.from_backend_state(raw_state)

        assert summary is not None
        assert summary.draft_total == 18
        assert summary.draft_target_total == 45
