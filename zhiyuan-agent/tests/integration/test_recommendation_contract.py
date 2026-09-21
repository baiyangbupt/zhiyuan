"""B4：比较矩阵的口径合同（Python 侧守约检查）。

Python 不重算矩阵，只检查 Java 返回的矩阵有没有违反合同。
两份实现同一个规则迟早会分叉，而分叉的表现是"把不可比的数放在一起比"——
错了也看不出来，所以这里只守底线。
"""
from __future__ import annotations

import pytest

from app.mcp_server.tools_recommendation import (
    comparable,
    comparison_problems,
    unavailable_dimensions,
)


def _entity(entity_id: str, **overrides) -> dict:
    entity = {
        "entityId": entity_id,
        "schoolId": "s-" + entity_id,
        "admissionYear": 2026,
        "areaId": "31",
        "batch": "本科批",
        "admissionMode": "major",
        "rateUnit": "percent",
        "admissionRatio": 45.0,
        "finalScore": 80.0,
        "planNum": 20,
        "tuitionPerYear": 6000,
        "cityName": "杭州",
    }
    entity.update(overrides)
    return entity


def _payload(entities: list, dimensions=None, cells=None, unavailable=None) -> dict:
    return {
        "entities": entities,
        "dimensions": dimensions or ["admissionRatio", "finalScore"],
        "cells": cells if cells is not None else [],
        "unavailableDimensions": unavailable or [],
    }


def test_comparable_requires_every_scope_field() -> None:
    assert comparable(_entity("e1"), _entity("e2")) is True
    assert comparable(_entity("e1"), _entity("e2", admissionYear=2025)) is False
    assert comparable(_entity("e1"), _entity("e2", batch="专科批")) is False


def test_a_missing_scope_field_is_not_treated_as_matching() -> None:
    # 缺 areaId 时不能判"同口径"：不知道口径是否相同，与相同是两件事。
    assert comparable(_entity("e1"), _entity("e2", areaId=None)) is False
    assert comparable(_entity("e1", areaId=None), _entity("e2", areaId=None)) is False


def test_a_matrix_with_numbers_under_mismatched_scope_is_rejected() -> None:
    entities = [_entity("e1", admissionYear=2025), _entity("e2", admissionYear=2026)]
    cells = [
        {"entityId": "e1", "dimension": "admissionRatio", "value": 45.0,
         "unit": "percent", "source": "entity.admissionRatio"},
        {"entityId": "e2", "dimension": "admissionRatio", "value": 50.0,
         "unit": "percent", "source": "entity.admissionRatio"},
    ]

    problems = comparison_problems(_payload(entities, cells=cells))

    # 2025 的率和 2026 的率放在一张表里比，方向不明。
    assert any(problem.startswith("comparison_incomparable_value") for problem in problems)


def test_a_conforming_matrix_has_no_problems() -> None:
    entities = [_entity("e1"), _entity("e2")]
    cells = [
        {"entityId": "e1", "dimension": "admissionRatio", "value": 45.0,
         "unit": "percent", "source": "entity.admissionRatio"},
        {"entityId": "e2", "dimension": "admissionRatio", "value": 50.0,
         "unit": "percent", "source": "entity.admissionRatio"},
    ]

    assert comparison_problems(_payload(entities, cells=cells)) == []


def test_a_cell_without_a_source_is_rejected() -> None:
    entities = [_entity("e1"), _entity("e2")]
    cells = [
        {"entityId": "e1", "dimension": "finalScore", "value": 80.0, "unit": "score"},
        {"entityId": "e2", "dimension": "finalScore", "value": 82.0, "unit": "score"},
    ]

    problems = comparison_problems(_payload(entities, dimensions=["finalScore"], cells=cells))

    # 没有来源的格子无法被核对，而核对不了的数字和没有数字一样没用。
    assert any(problem.startswith("comparison_cell_without_source") for problem in problems)


def test_a_missing_value_must_say_why() -> None:
    entities = [_entity("e1"), _entity("e2", tuitionPerYear=None)]
    cells = [
        {"entityId": "e1", "dimension": "tuitionPerYear", "value": 6000,
         "unit": "cny_per_year", "source": "entity.tuitionPerYear"},
        {"entityId": "e2", "dimension": "tuitionPerYear", "value": None, "unit": "cny_per_year",
         "source": "entity.tuitionPerYear"},
    ]

    problems = comparison_problems(_payload(entities, dimensions=["tuitionPerYear"], cells=cells))

    assert any(problem.startswith("comparison_missing_reason") for problem in problems)


def test_an_unknown_dimension_is_rejected() -> None:
    entities = [_entity("e1"), _entity("e2")]

    problems = comparison_problems(_payload(entities, dimensions=["secretField"]))

    assert any(problem.startswith("comparison_dimension_unsupported") for problem in problems)


def test_entity_count_is_bounded() -> None:
    assert "comparison_entity_count_invalid" in comparison_problems(_payload([_entity("e1")]))
    many = [_entity(f"e{index}") for index in range(6)]
    assert "comparison_entity_count_invalid" in comparison_problems(_payload(many))


def test_name_dimensions_are_not_scope_bound() -> None:
    # 城市名不随年份变化，口径不一致时仍然可读。
    entities = [_entity("e1", admissionYear=2025), _entity("e2", admissionYear=2026)]
    cells = [
        {"entityId": "e1", "dimension": "cityName", "value": "杭州", "source": "entity.cityName"},
        {"entityId": "e2", "dimension": "cityName", "value": "北京", "source": "entity.cityName"},
    ]

    problems = comparison_problems(_payload(entities, dimensions=["cityName"], cells=cells))

    assert problems == []


def test_unavailable_dimensions_are_reported_for_the_ui() -> None:
    payload = _payload([_entity("e1"), _entity("e2")], unavailable=["planNum", "tuitionPerYear"])

    assert unavailable_dimensions(payload) == ["planNum", "tuitionPerYear"]
    assert unavailable_dimensions({}) == []
