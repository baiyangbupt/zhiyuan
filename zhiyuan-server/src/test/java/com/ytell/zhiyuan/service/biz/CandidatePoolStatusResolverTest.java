package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

public class CandidatePoolStatusResolverTest {

    @Test
    void shouldResolveNotGeneratedForMissingPool() {
        assertEquals("not_generated", CandidatePoolStatusResolver.resolveStatus(null));
        assertEquals(0, CandidatePoolStatusResolver.resolveRequiredCandidateCount(null));
    }

    @Test
    void shouldResolveEmptyWhenNoCandidateTotalsExist() {
        CandidatePoolStateDTO state = new CandidatePoolStateDTO();
        state.setRequiredCount(3);

        assertEquals("empty", CandidatePoolStatusResolver.resolveStatus(state));
    }

    @Test
    void shouldResolveLowCountByMajorCandidateTotal() {
        CandidatePoolStateDTO state = new CandidatePoolStateDTO();
        state.setVolunteerModel("major");
        state.setRequiredCount(5);
        state.getSummary().setTotal(3);

        assertEquals(5, CandidatePoolStatusResolver.resolveRequiredCandidateCount(state));
        assertEquals("low_count", CandidatePoolStatusResolver.resolveStatus(state));
    }

    @Test
    void shouldResolveLowCountByMajorGroupUnitTotal() {
        CandidatePoolStateDTO state = new CandidatePoolStateDTO();
        state.setVolunteerModel("majorGroup");
        state.setRequiredUnitCount(5);
        state.setRequiredCount(30);
        state.getSummary().setUnitTotal(3);
        state.getSummary().setTotal(18);

        assertEquals(5, CandidatePoolStatusResolver.resolveRequiredCandidateCount(state));
        assertEquals("low_count", CandidatePoolStatusResolver.resolveStatus(state));
    }

    @Test
    void shouldResolveReadyWhenEnoughCandidatesExist() {
        CandidatePoolStateDTO state = new CandidatePoolStateDTO();
        state.setVolunteerModel("major");
        state.setRequiredCount(3);
        state.getSummary().setTotal(6);

        assertEquals("ready", CandidatePoolStatusResolver.resolveStatus(state));
    }

    @Test
    void shouldFallbackToRequiredUnitCountWhenRequiredCountIsMissing() {
        CandidatePoolStateDTO state = new CandidatePoolStateDTO();
        state.setVolunteerModel("major");
        state.setRequiredUnitCount(4);
        state.getSummary().setTotal(4);

        assertEquals(4, CandidatePoolStatusResolver.resolveRequiredCandidateCount(state));
        assertEquals("ready", CandidatePoolStatusResolver.resolveStatus(state));
    }
}
