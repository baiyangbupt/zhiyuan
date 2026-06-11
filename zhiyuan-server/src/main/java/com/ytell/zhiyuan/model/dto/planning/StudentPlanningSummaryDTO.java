package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class StudentPlanningSummaryDTO {
    private String sex;
    private Integer score;
    private Integer rank;
    private String batchName;
    private Integer batchScore;
    private String provinceName;
    private List<String> subjects = Lists.newArrayList();
    private List<String> strengthSubjects = Lists.newArrayList();
}
