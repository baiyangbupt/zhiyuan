package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CompiledActionDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.ObjectiveDeltaDTO;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * ObjectiveDelta → CompiledAction（J5.2）。
 *
 * <p>审查 finding 只带 delta；修复策略与目标由这里统一编译。当前只产出意图，
 * 不直接执行——执行仍走 proposal → pending → 用户确认。`executable=false` 是
 * 刻意的：在接线到修复提案生成前，不允许任何路径把 finding 当命令执行。</p>
 */
public class ActionCompiler {

    public CompiledActionDTO compile(ObjectiveDeltaDTO delta) {
        if (delta == null || Strings.isNullOrEmpty(delta.getStrategy())) {
            return null;
        }
        CompiledActionDTO action = new CompiledActionDTO();
        action.setStrategy(delta.getStrategy());
        action.setSourceCheck(delta.getSourceCheck());
        action.setReasonCode(delta.getReasonCode());
        action.setTargets(collectTargets(delta));
        action.setExecutable(false);
        action.setNote("preview_only_until_confirmation");
        return action;
    }

    private List<EvaluationEntryRefDTO> collectTargets(ObjectiveDeltaDTO delta) {
        List<EvaluationEntryRefDTO> targets = Lists.newArrayList();
        Set<String> seen = new HashSet<String>();
        append(targets, seen, delta.getRemoveTargets());
        append(targets, seen, delta.getReorderTargets());
        append(targets, seen, delta.getAddTargets());
        return targets;
    }

    private void append(List<EvaluationEntryRefDTO> targets, Set<String> seen,
                        List<EvaluationEntryRefDTO> refs) {
        if (refs == null) {
            return;
        }
        for (EvaluationEntryRefDTO ref : refs) {
            if (ref == null || Strings.isNullOrEmpty(ref.getId())) {
                continue;
            }
            String key = String.valueOf(ref.getLevel()) + ":" + ref.getId();
            if (seen.add(key)) {
                targets.add(ref);
            }
        }
    }
}
