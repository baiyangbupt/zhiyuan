package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanningUnitDTO {
    private String unitId;
    private String planSchoolDataId;
    private String schoolId;
    private String schoolName;
    private String provinceName;
    private String cityName;
    // 区域 ID（随候选带上来 ✓）：组模式的区域判定按 ID 优先 ✓。
    private String provinceId;
    private String cityId;
    private String schoolLevel;
    private String schoolNature;
    private String schoolCategory;
    private String tier;
    private Double schoolEnrollRatio;
    private Double finalScore;
    private Double intentScore;
    private Double futureDevelopmentScore;
    private Double admissionRatio;
    private Boolean preferred = false;
    private Integer requiredMajorCount = 0;
    private Boolean complete = false;
    private Boolean hasSafetyMajor = false;
    private Integer selectedMajorCount = 0;
    private Integer totalMajorCount = 0;
    private List<PlanningUnitMajorDTO> selectedMajors = Lists.newArrayList();
    private List<PlanningUnitMajorDTO> allMajors = Lists.newArrayList();
}
