package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class FixProposalStateDTO {
    private String status = "idle";
    private String proposalSource = "review_check";
    private Integer sourceVersion;
    private Integer sourceReviewVersion;
    private Integer sourceVersionGuard;
    private Integer total = 0;
    private List<FixProposalDTO> proposals = Lists.newArrayList();
}
