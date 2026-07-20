package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class TierAllocationResolutionDTO {
    private Integer targetCount;
    private TierAllocationConstraintDTO effectiveBounds;
    private TierWeightsDTO canonicalWeights;
    private TierCountsDTO resolvedCounts;
    private String resolutionMethod;
    private List<String> tieBreakOrder = Lists.newArrayList("sprint", "stable", "protect");
    private String objectiveDigest;
    private String solverVersion;
}
