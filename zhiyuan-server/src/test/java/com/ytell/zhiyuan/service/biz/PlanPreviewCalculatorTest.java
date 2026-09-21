package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.FrozenPlanPayloadDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertNull;

public class PlanPreviewCalculatorTest {

    @Test
    void deepCopyIsIndependentFromTheSource() {
        PlanningStateDTO source = new PlanningStateDTO();
        source.setSessionId(101L);
        source.setVersion(7);

        PlanningStateDTO copy = PlanPreviewCalculator.deepCopy(source);

        // 副本必须与原对象断开：只要有一个字段是引用传递的，演算就会
        // 顺着引用改到真实状态上——那正是"预览把正式表改了"的成因。
        assertNotSame(source, copy);
        copy.setVersion(99);
        assertEquals(7, source.getVersion(), "改副本不该动到原对象");
    }

    @Test
    void deepCopyOfNullIsNull() {
        assertNull(PlanPreviewCalculator.deepCopy(null));
    }

    @Test
    void constituentDigestsAreSeparateNotMerged() {
        FrozenPlanPayloadDTO frozen = new FrozenPlanPayloadDTO();
        frozen.setObjectiveDigest(PlanPreviewCalculator.digest("goal-A"));
        frozen.setCandidateDigest(PlanPreviewCalculator.digest("candidates-A"));
        frozen.setProfileDigest(PlanPreviewCalculator.digest("profile-A"));
        frozen.setSolverVersion("ojalgo-1");
        String baseline = PlanPreviewCalculator.payloadDigest(frozen);

        // 只换目标：候选与画像没变，但载荷摘要必须变——否则用户改了目标之后
        // 系统会说"和刚才那份一样"。
        FrozenPlanPayloadDTO goalChanged = copyOf(frozen);
        goalChanged.setObjectiveDigest(PlanPreviewCalculator.digest("goal-B"));

        assertNotEquals(baseline, PlanPreviewCalculator.payloadDigest(goalChanged));

        // 只换候选：同理。
        FrozenPlanPayloadDTO candidateChanged = copyOf(frozen);
        candidateChanged.setCandidateDigest(PlanPreviewCalculator.digest("candidates-B"));
        assertNotEquals(baseline, PlanPreviewCalculator.payloadDigest(candidateChanged));

        // 只换求解器版本：同一份输入换求解器，产物也可能不同，所以也要变。
        FrozenPlanPayloadDTO solverChanged = copyOf(frozen);
        solverChanged.setSolverVersion("ojalgo-2");
        assertNotEquals(baseline, PlanPreviewCalculator.payloadDigest(solverChanged));
    }

    @Test
    void tracesDoNotParticipateInThePayloadDigest() {
        FrozenPlanPayloadDTO frozen = new FrozenPlanPayloadDTO();
        frozen.setObjectiveDigest(PlanPreviewCalculator.digest("goal-A"));
        frozen.setCandidateDigest(PlanPreviewCalculator.digest("candidates-A"));
        frozen.setProfileDigest(PlanPreviewCalculator.digest("profile-A"));
        frozen.setSolverVersion("ojalgo-1");
        String baseline = PlanPreviewCalculator.payloadDigest(frozen);

        // trace 是**解释**，不是产物。把它算进摘要，会让"内容没变但 trace 变长"
        // 被判成载荷变了，于是同一个方案反复触发重新确认。
        frozen.setSelectionTrace("solver selected 20 units");
        frozen.setOrderingTrace("ordered by tier");

        assertEquals(baseline, PlanPreviewCalculator.payloadDigest(frozen));
    }

    @Test
    void selectionAndOrderingTracesLiveInSeparateFields() {
        FrozenPlanPayloadDTO frozen = new FrozenPlanPayloadDTO();

        // selection 与 ordering 是两次独立求解，输入不同。合并成一个 trace
        // 会让"到底是选择变了还是排序变了"查不出来。
        frozen.setSelectionTrace("selection-trace");
        frozen.setOrderingTrace("ordering-trace");
        assertEquals("selection-trace", frozen.getSelectionTrace());
        assertEquals("ordering-trace", frozen.getOrderingTrace());
    }

    @Test
    void digestOfNullPayloadIsNull() {
        assertNull(PlanPreviewCalculator.payloadDigest(null));
    }

    private static FrozenPlanPayloadDTO copyOf(FrozenPlanPayloadDTO source) {
        FrozenPlanPayloadDTO copy = new FrozenPlanPayloadDTO();
        copy.setObjectiveDigest(source.getObjectiveDigest());
        copy.setCandidateDigest(source.getCandidateDigest());
        copy.setProfileDigest(source.getProfileDigest());
        copy.setSolverVersion(source.getSolverVersion());
        return copy;
    }
}
