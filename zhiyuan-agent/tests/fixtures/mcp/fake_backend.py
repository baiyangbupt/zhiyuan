#!/usr/bin/env python3
"""Deterministic backend fixture used by Domain MCP unit tests and self-check."""

from __future__ import annotations


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def resolve(self, **kwargs):
        self.calls.append(("resolve", kwargs))
        query = kwargs.get("query", "")
        if query in {"华师大", "师大"}:
            return {
                "status": "needs_clarification",
                "data": {"candidates": [{"entityId": "school-sh-1", "name": "华东师范大学"}]},
            }
        return {"status": "ok", "data": {"entityId": "school-1", "name": query}}

    async def search_schools(self, **kwargs):
        self.calls.append(("search_schools", kwargs))
        return {"items": [{"schoolId": "school-1", "name": "浙江大学"}]}

    async def get_school(self, **kwargs):
        self.calls.append(("get_school", kwargs))
        return {"schoolId": kwargs.get("schoolId"), "name": "浙江大学"}

    async def search_majors(self, **kwargs):
        self.calls.append(("search_majors", kwargs))
        return {"items": [{"majorId": "major-1", "name": kwargs.get("query", "计算机科学与技术")}]}

    async def get_major(self, **kwargs):
        self.calls.append(("get_major", kwargs))
        return {"majorId": kwargs.get("majorId"), "name": "计算机科学与技术"}

    async def get_current_plan(self, **kwargs):
        self.calls.append(("get_current_plan", kwargs))
        mode = kwargs.get("admissionMode", "major")
        return {
            "admissionMode": mode,
            "admissionFacts": [
                {
                    "admissionMode": mode,
                    "admissionUnitId": "unit-major-group-1" if mode == "major_group" else "unit-major-1",
                    "schoolId": "school-1",
                    **({"groupCode": "101"} if mode == "major_group" else {"majorId": "major-1"}),
                    "unitAdmissionRate": 45,
                    "riskTier": "冲",
                    "majorItems": ([{"majorId": "major-1", "majorAdmissionRate": 85}] if mode == "major_group" else []),
                }
            ],
            "dataVersion": "2026.09.07",
            "algorithmVersion": "rate-v3",
        }

    async def get_history(self, **kwargs):
        self.calls.append(("get_history", kwargs))
        mode = kwargs.get("admissionMode", "major")
        return {
            "admissionMode": mode,
            "admissionFacts": [{
                "admissionMode": mode,
                "admissionUnitId": "unit-history-group-1" if mode == "major_group" else "unit-history-major-1",
                "schoolId": kwargs.get("schoolId", "school-1"),
                **({"groupCode": kwargs.get("groupCode", "101")} if mode == "major_group" else {"majorId": kwargs.get("majorId", "major-1")}),
                "unitAdmissionRate": 70,
                "riskTier": "保",
                "majorItems": ([{"majorId": "major-1", "majorAdmissionRate": 40}] if mode == "major_group" else []),
            }],
            "dataVersion": "2026.09.07",
            "algorithmVersion": "rate-v3",
            "scope": "school-major",
            "coverage": "complete",
            "comparability": "comparable",
            "limitations": [],
        }

    async def check_eligibility(self, **kwargs):
        self.calls.append(("check_eligibility", kwargs))
        mode = kwargs.get("admissionMode", "major")
        return {
            "eligible": True,
            "reasons": [],
            "admissionMode": mode,
            "admissionFacts": [],
            "dataVersion": "2026.09.07",
        }
