package com.ytell.zhiyuan.model.dto.gaotu.res;

import lombok.Data;

/**
 * 学校招生章程（上游 `SchoolRuleResponse` 的镜像）。
 *
 * <p>**这不是"章程原文"的可靠来源**：上游在"该校没有规则"时回的是配置的占位文案
 * （默认 `正在更新中`，见 `hl.ci.school.rule.default.content`），而且**响应里没有
 * 标志位**区分"真章程"与"占位文案"。消费方必须自己判断，不能直接当原文引用。
 */
@Data
public class SchoolRuleRes {
    private String title;
    private String content;
}
