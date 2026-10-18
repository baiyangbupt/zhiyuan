package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 从 `ObjectiveDelta` 编译出的动作意图（J5.2）。
 *
 * <p>它是审查 finding 与既有修复提案之间的**唯一桥**：策略/目标都从 delta 来，
 * 不允许 finding 自己再带一套不同的修复建议。当前 `executable=false`：
 * 编译器只产出意图，真正执行仍走既有 proposal → pending → confirm 链。</p>
 */
@Data
public class CompiledActionDTO {
    private String strategy;
    private String sourceCheck;
    private String reasonCode;
    private List<EvaluationEntryRefDTO> targets = Lists.newArrayList();
    private Boolean executable = false;
    private String note;
}
