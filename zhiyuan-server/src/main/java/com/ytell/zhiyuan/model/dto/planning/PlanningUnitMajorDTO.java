package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanningUnitMajorDTO {
    private String volunteerId;
    private String majorId;
    private String majorName;
    private String majorCode;
    private String majorCategoryId;
    private String majorSubCategoryId;
    /**
     * 分类**名**（专业类/门类 ✓，如 `"临床医学类"`/`"医学"` ✓）。
     *
     * <p>组模式的"专业筛选"判在**单元**这一层（`RepairCandidateEligibility` 把单元专业
     * 转成候选再比对 ✓），缺了这两个名字，`"医学类"` 这类范围在单元侧**一条都中不了** ✗
     * （2026-10-08 真栈：只留"医学类"→ 候选侧已能留 17 条，单元侧仍判全部违反 → 40905 ✗）。
     * 旧数据没有这两个字段 → 反序列化为 null → 退回按专业名匹配 ✓（与改动前一致 ✓）。
     */
    private String majorCategory;
    private String majorDiscipline;
    private String tier;
    private Double admissionRatio;
    private Double finalScore;
    private Double intentScore;
    private Boolean preferred = false;
    private Boolean selected = false;
    private Boolean safetyMajor = false;
    private Integer tuitionPerYear;
    private Integer rankInTier;
    private List<String> reasonCodes = Lists.newArrayList();
    private List<String> majorPlanTags = Lists.newArrayList();
}
