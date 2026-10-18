package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class StudentPlanningSummaryDTO {
    private String sex;
    private Integer examYear;
    private Integer score;
    private Integer rank;
    private String batchName;
    private Integer batchScore;
    private String provinceName;
    /** 科类（“物理/历史/综合”）；desc 为空时回落 code（WL/LS/N）。 */
    private String subjectType;
    private List<String> subjects = Lists.newArrayList();
    private List<String> strengthSubjects = Lists.newArrayList();
}
