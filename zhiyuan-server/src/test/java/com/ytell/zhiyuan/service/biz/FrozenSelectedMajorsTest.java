package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 两阶段组内专业选择（selectedMajorIdsByUnit）参与冻结摘要与 apply 前复核。
 */
class FrozenSelectedMajorsTest {

    @Test
    void selectedMajorsChangeDigest() {
        PlanningStateDTO state = state();
        List<CandidateItemDTO> candidates = candidates();
        String digest = FrozenSelectionDigest.compute(state, candidates,
                proposal("u1", majors("u1", "u1_v1", "u1_v2")));
        assertEquals(digest, FrozenSelectionDigest.compute(state, candidates,
                proposal("u1", majors("u1", "u1_v2", "u1_v1"))),
                "专业顺序不应影响摘要");
        assertNotEquals(digest, FrozenSelectionDigest.compute(state, candidates,
                proposal("u1", majors("u1", "u1_v1", "u1_v3"))),
                "专业选择变化必须改变摘要");
        assertNotEquals(digest, FrozenSelectionDigest.compute(state, candidates,
                proposal("u1", null)),
                "无专业选择与有专业选择必须产生不同摘要");
    }

    @Test
    void emptySelectedMajorsKeepsLegacyDigest() {
        PlanningStateDTO state = state();
        List<CandidateItemDTO> candidates = candidates();
        // 旧冻结结果反序列化后通常拿到默认空 map，而不是 null；两种都应与旧摘要一致。
        FixProposalDTO absent = proposal("u1", null);
        FixProposalDTO empty = proposal("u1", new LinkedHashMap<String, List<String>>());

        String digest = FrozenSelectionDigest.compute(state, candidates, empty);
        assertEquals(digest, FrozenSelectionDigest.compute(state, candidates, absent));
        assertDoesNotThrow(() -> FrozenSelectionGuard.verify(
                state, candidates, absent, digest));
    }

    @Test
    void guardRejectsMissingSelectedMajor() {
        PlanningStateDTO state = state();
        List<CandidateItemDTO> candidates = candidates();
        FixProposalDTO proposal = proposal("u1", majors("u1", "u1_v1", "u1_missing"));
        String digest = FrozenSelectionDigest.compute(state, candidates, proposal);

        BusinessException error = assertThrows(BusinessException.class,
                () -> FrozenSelectionGuard.verify(state, candidates, proposal, digest));
        assertTrue(error.getMessage().contains("solver_input_stale"));
        assertTrue(error.getMessage().contains("u1_missing"));
    }

    @Test
    void guardRejectsMajorUnitNotInSelectedEntities() {
        PlanningStateDTO state = state();
        List<CandidateItemDTO> candidates = candidates();
        FixProposalDTO proposal = proposal("u1", majors("u2", "u2_v1"));
        String digest = FrozenSelectionDigest.compute(state, candidates, proposal);

        BusinessException error = assertThrows(BusinessException.class,
                () -> FrozenSelectionGuard.verify(state, candidates, proposal, digest));
        assertTrue(error.getMessage().contains("solver_input_stale"));
    }

    @Test
    void guardAcceptsDeclaredMajorsPresentInRawCandidates() {
        PlanningStateDTO state = state();
        List<CandidateItemDTO> candidates = candidates();
        FixProposalDTO proposal = proposal("u1", majors("u1", "u1_v1", "u1_v2"));
        String digest = FrozenSelectionDigest.compute(state, candidates, proposal);
        assertDoesNotThrow(() -> FrozenSelectionGuard.verify(
                state, candidates, proposal, digest));
    }

    private PlanningStateDTO state() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        return state;
    }

    private List<CandidateItemDTO> candidates() {
        return Arrays.asList(
                candidate("u1_v1", "u1", "计算机"),
                candidate("u1_v2", "u1", "软件工程"),
                candidate("u1_v3", "u1", "人工智能"),
                candidate("u2_v1", "u2", "金融学"));
    }

    private CandidateItemDTO candidate(String volunteerId, String unitId, String major) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setSchoolId(unitId);
        candidate.setSchoolName("学校" + unitId);
        candidate.setDisplaySchoolName("学校" + unitId);
        candidate.setMajorName(major);
        candidate.setTier("稳");
        return candidate;
    }

    private Map<String, List<String>> majors(String unitId, String... volunteerIds) {
        Map<String, List<String>> result = new LinkedHashMap<String, List<String>>();
        result.put(unitId, Lists.newArrayList(volunteerIds));
        return result;
    }

    private FixProposalDTO proposal(String selectedEntityId,
                                    Map<String, List<String>> selectedMajorIdsByUnit) {
        PlanSolverResultDTO result = new PlanSolverResultDTO();
        result.setSelectedEntityIds(Lists.newArrayList(selectedEntityId));
        result.setSelectedMajorIdsByUnit(selectedMajorIdsByUnit);
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setSolverResult(result);
        return proposal;
    }
}
