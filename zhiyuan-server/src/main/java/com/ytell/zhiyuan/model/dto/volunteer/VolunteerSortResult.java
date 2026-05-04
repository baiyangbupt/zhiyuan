package com.ytell.zhiyuan.model.dto.volunteer;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 志愿排序结果
 */
@Data
public class VolunteerSortResult {
    private List<VolunteerSchoolGroup> sortedSchoolGroups; // 排序后的院校专业组列表
    private Map<String, Object> sortInfo; // 排序相关信息
    private String applyType; // 报考类型
    private List<String> warnings; // 排序过程中的警告信息

    public VolunteerSortResult() {
    }

    public VolunteerSortResult(List<VolunteerSchoolGroup> sortedSchoolGroups,
                               Map<String, Object> sortInfo,
                               String applyType,
                               List<String> warnings) {
        this.sortedSchoolGroups = sortedSchoolGroups;
        this.sortInfo = sortInfo;
        this.applyType = applyType;
        this.warnings = warnings;
    }
}
