package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReviewFixPreviewDTO {
    private String status = "preview_only";
    private String proposalSource = "review_check";
    private Integer sourceVersion;
    private ReviewStateDTO review;
    private List<FixProposalDTO> proposals = Lists.newArrayList();
}
