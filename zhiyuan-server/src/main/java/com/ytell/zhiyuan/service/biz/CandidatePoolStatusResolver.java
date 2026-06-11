package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;

final class CandidatePoolStatusResolver {

    private CandidatePoolStatusResolver() {
    }

    static String resolveStatus(CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return "not_generated";
        }
        int effectiveTotal = candidatePoolState.getSummary() == null ? 0 : valueOrZero(candidatePoolState.getSummary().getTotal());
        int effectiveUnitTotal = candidatePoolState.getSummary() == null ? 0 : valueOrZero(candidatePoolState.getSummary().getUnitTotal());
        int required = resolveRequiredCandidateCount(candidatePoolState);
        if (effectiveTotal <= 0 && effectiveUnitTotal <= 0) {
            return "empty";
        }
        if (required > 0) {
            int effective = isMajorGroupMode(candidatePoolState) ? effectiveUnitTotal : effectiveTotal;
            if (effective > 0 && effective < required) {
                return "low_count";
            }
        }
        return "ready";
    }

    static int resolveRequiredCandidateCount(CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return 0;
        }
        if (isMajorGroupMode(candidatePoolState) && candidatePoolState.getRequiredUnitCount() != null) {
            return candidatePoolState.getRequiredUnitCount();
        }
        if (candidatePoolState.getRequiredCount() != null) {
            return candidatePoolState.getRequiredCount();
        }
        if (candidatePoolState.getRequiredUnitCount() != null) {
            return candidatePoolState.getRequiredUnitCount();
        }
        return 0;
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static int valueOrZero(Integer value) {
        return value == null ? 0 : value;
    }
}
