package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class DataFreshnessCheckReq {
    private String source = "gaotu";
    private String requestHash;
    private String dataHash;
    private String dataVersion;
    private String changeLevel;
    private String summary;
    private String detail;
    private Integer changedCount;
    private Integer addedCount;
    private Integer removedCount;
    private Integer updatedCount;
    private Integer invalidCount;
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<String> affectedUnitIds = Lists.newArrayList();
    private Boolean markStale = true;
    private Boolean fetchLatest = false;
    private Boolean syncSourceData = false;
}
