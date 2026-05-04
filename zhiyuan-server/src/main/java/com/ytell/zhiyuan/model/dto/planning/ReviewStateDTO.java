package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReviewStateDTO {
    private String status = "idle";
    private String reviewedAt;
    private Integer sourceVersion;
    private ReviewSummaryDTO summary = new ReviewSummaryDTO();
    private List<ReviewCheckDTO> checks = Lists.newArrayList();
    private CompensationPreviewDTO compensationPreview = new CompensationPreviewDTO();
}
