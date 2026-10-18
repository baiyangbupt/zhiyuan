"""共享的方案规则字段枚举。

`contracts.py`（模型输出契约）与 `intent_draft.py`（完整意图草稿）都要描述
同一组 Java 白名单字段；放在独立模块避免两边各写一份后漂移，也避免循环导入。
"""

from __future__ import annotations

from typing import Literal

ProposalRuleDomain = Literal["region", "major", "school", "admission"]

ProposalRuleKey = Literal[
    "province",
    "city",
    "area",
    "region_group",
    "major",
    "level1",
    "level2",
    "level3",
    "major_tag",
    "school",
    "schools",
    "school_nature",
    "program_type",
    "school_category",
    "school_level",
    "school_tag",
    "tier",
]
