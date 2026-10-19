package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.ObjectiveDeltaDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class PlanCommandCompilerTest {
    private final PlanCommandCompiler compiler = new PlanCommandCompiler();

    @Test
    void requiresCompleteEvaluationProvenanceBeforeIssuingCommand() {
        EvaluationContextDTO context = context();
        context.setPlanContentDigest(null);
        assertNull(compiler.compile(delta(), context));
    }

    @Test
    void canonicalDigestTreatsRemovalAsSetButReorderingAsOrderedSequence() {
        ObjectiveDeltaDTO delta = delta();
        delta.setRemoveTargets(Lists.newArrayList(ref("unit", "1"), ref("unit", "2")));
        String first = compiler.compile(delta, context()).getCommandDigest();
        delta.setRemoveTargets(Lists.newArrayList(ref("unit", "2"), ref("unit", "1")));
        assertEquals(first, compiler.compile(delta, context()).getCommandDigest());

        delta.setReorderTargets(Lists.newArrayList(ref("unit", "1"), ref("unit", "2")));
        String ordered = compiler.compile(delta, context()).getCommandDigest();
        delta.setReorderTargets(Lists.newArrayList(ref("unit", "2"), ref("unit", "1")));
        assertNotEquals(ordered, compiler.compile(delta, context()).getCommandDigest());
    }

    @Test
    void copiesMutableInputsAndKeepsDifferentCoverageIdentitiesSeparate() {
        ObjectiveDeltaDTO delta = delta();
        delta.getRemoveTargets().add(ref("unit", "1"));
        CoverageRequirementDTO region = new CoverageRequirementDTO();
        region.setDomain("region");
        region.setKey("province");
        region.setValues(Lists.newArrayList("浙江"));
        CoverageRequirementDTO major = new CoverageRequirementDTO();
        major.setDomain("major");
        major.setKey("category");
        major.setValues(Lists.newArrayList("浙江"));
        delta.setCoverageRequirements(Lists.newArrayList(region, major));
        PlanCommandDTO command = compiler.compile(delta, context());

        assertEquals(2, command.getCoverageRequirements().size());
        command.getForcedRemoveTargets().get(0).setId("other");
        command.getCoverageRequirements().get(0).getValues().clear();
        assertEquals("1", delta.getRemoveTargets().get(0).getId());
        assertEquals(Lists.newArrayList("浙江"), region.getValues());
        assertEquals(Lists.newArrayList("浙江"), major.getValues());
    }

    @Test
    void rejectsUnknownStrategiesAndIncompleteFillTargets() {
        ObjectiveDeltaDTO delta = delta();
        delta.setStrategy("unrecognized_strategy");
        assertNull(compiler.compile(delta, context()));
        delta.setStrategy("fill_missing_count");
        assertNull(compiler.compile(delta, context()));
    }

    @Test
    void rejectsIncompleteExplicitReferencesInsteadOfSilentlyShrinkingTheAction() {
        ObjectiveDeltaDTO delta = delta();
        delta.setRemoveTargets(Lists.newArrayList(ref("unit", "1"), ref("unit", null)));
        assertNull(compiler.compile(delta, context()));
        delta.setRemoveTargets(Lists.newArrayList(ref(null, "1")));
        assertNull(compiler.compile(delta, context()));
        delta.setRemoveTargets(Lists.newArrayList(ref("unit", "  ")));
        assertNull(compiler.compile(delta, context()));
    }

    @Test
    void equivalentConstraintSetsHaveTheSameDigestWithoutMutatingInput() {
        ObjectiveDeltaDTO delta = delta();
        delta.getConstraintPatch().put("mustExcludeRegionIds", Lists.newArrayList("2", "1"));
        String first = compiler.compile(delta, context()).getCommandDigest();
        assertEquals(Lists.newArrayList("2", "1"), delta.getConstraintPatch().get("mustExcludeRegionIds"));
        delta.getConstraintPatch().put("mustExcludeRegionIds", Lists.newArrayList("1", "2", "1"));
        assertEquals(first, compiler.compile(delta, context()).getCommandDigest());
        delta.getConstraintPatch().put("mustExcludeRegionIds", Lists.newArrayList("1", "3"));
        assertNotEquals(first, compiler.compile(delta, context()).getCommandDigest());
    }

    @Test
    void emptyMajorPlanStillCompilesAtVolunteerGranularity() {
        ObjectiveDeltaDTO delta = delta();
        delta.setStrategy("fill_missing_count");
        delta.setTargetCount(5);
        EvaluationContextDTO context = context();
        context.setAdmissionMode("major");
        assertEquals("volunteer", compiler.compile(delta, context).getLevel());
    }

    private EvaluationContextDTO context() {
        EvaluationContextDTO context = new EvaluationContextDTO();
        context.setPlanContentDigest("plan");
        context.setEvaluatedStateVersion(7);
        return context;
    }

    private ObjectiveDeltaDTO delta() {
        ObjectiveDeltaDTO delta = new ObjectiveDeltaDTO();
        delta.setStrategy("remove_risk_items");
        delta.setSourceCheck("admission_limit");
        return delta;
    }

    private EvaluationEntryRefDTO ref(String level, String id) {
        EvaluationEntryRefDTO ref = new EvaluationEntryRefDTO();
        ref.setLevel(level);
        ref.setId(id);
        return ref;
    }
}
