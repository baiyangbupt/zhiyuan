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
    /** 专项资格只读投影：null=未回答，false=明确无专项，true=有某种专项（类别待核验）。 */
    private Boolean specialPlan;
    private List<String> subjects = Lists.newArrayList();
    private List<String> strengthSubjects = Lists.newArrayList();
}
