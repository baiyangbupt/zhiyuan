package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** S0b：pending 里冻结的 proposal 必须能完整往返 JSON。 */
class FixProposalFreezeTest {

    @Test
    void frozenProposalRoundTripKeepsSolverSelection() {
        PlanSolverResultDTO solverResult = new PlanSolverResultDTO();
        solverResult.setStatus("ready");
        solverResult.setSolverVersion("staged-test");
        solverResult.setInputDigest("digest");
        solverResult.setSelectedEntityIds(Arrays.asList("a", "b"));
        solverResult.setOrderedEntityIds(Arrays.asList("b", "a"));
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("p1");
        proposal.setProposalSource("user_goal");
        proposal.setStrategy(RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT);
        proposal.setSolverResult(solverResult);
        proposal.setSolverVersion("staged-test");
        proposal.setSolverInputDigest("digest");

        JSONObject frozen = JSON.parseObject(JSON.toJSONString(proposal));
        FixProposalDTO parsed = JSON.parseObject(JSON.toJSONString(frozen), FixProposalDTO.class);

        assertEquals("p1", parsed.getProposalId());
        assertEquals(RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT, parsed.getStrategy());
        assertEquals(Arrays.asList("a", "b"), parsed.getSolverResult().getSelectedEntityIds());
        assertEquals(Arrays.asList("b", "a"), parsed.getSolverResult().getOrderedEntityIds());
        assertEquals("digest", parsed.getSolverResult().getInputDigest());
    }
}
