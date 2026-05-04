package com.ytell.zhiyuan.model.dto.volunteer;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 区间划分结果
 */
@Data
public class VolunteerIntervalResult {
    private Map<String, List<VolunteerSchoolGroup>> intervals; // 区间名称 -> 院校专业组列表
    private String applyType; // 报考类型
    private Integer totalCount; // 总志愿数

    public VolunteerIntervalResult() {
    }

    public VolunteerIntervalResult(Map<String, List<VolunteerSchoolGroup>> intervals,
                                   String applyType,
                                   Integer totalCount) {
        this.intervals = intervals;
        this.applyType = applyType;
        this.totalCount = totalCount;
    }
}
