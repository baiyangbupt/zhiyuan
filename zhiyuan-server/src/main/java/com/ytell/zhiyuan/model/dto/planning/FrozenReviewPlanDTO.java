package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class FrozenReviewPlanDTO {
    private DraftPlanStateDTO workingPlan;
    private OrderedPlanStateDTO orderedPlan;
    private List<String> selectedEntityIds = Lists.newArrayList();
    private List<String> orderedEntityIds = Lists.newArrayList();
    private List<CandidateItemDTO> selectedFacts = Lists.newArrayList();
    private String factsDigest;
}
