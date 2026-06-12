package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class DataFreshnessStateDTO {
    private String source = "gaotu";
    private String fetchTime;
    private String lastCheckedAt;
    private String examYear;
    private String prepareType;
    private String province;
    private String batch;
    private String subjectType;
    private Integer score;
    private String requestHash;
    private String dataHash;
    private String dataVersion;
    private String latestDataHash;
    private String latestDataVersion;
    private String statusCode = "unknown";
    private String changeLevel = "none";
    private Boolean shouldNotify = false;
    private Boolean requiresCandidateRefresh = false;
    private Boolean requiresReview = false;
    private String summary;
    private String detail;
    private Integer changedCount = 0;
    private Integer addedCount = 0;
    private Integer removedCount = 0;
    private Integer updatedCount = 0;
    private Integer invalidCount = 0;
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedReviewCodes = Lists.newArrayList();
}
