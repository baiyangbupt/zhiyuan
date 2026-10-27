package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 评价输入里的条目引用（unit 或 volunteer 粒度）。
 *
 * <p>`pathTier` 只来自校线档位（ordered item/unit 的 tier）；`schoolRatio` 只做
 * 证据/排序，`majorRatio` 只做组内证据，两者都不反写 `pathTier`。</p>
 */
@Data
public class EvaluationEntryRefDTO {
    private String level;
    private String id;
    private Integer position;
    private String schoolName;
    private String majorName;
    private List<String> selectedMajorNames = Lists.newArrayList();
    private String pathTier;
    private Double schoolRatio;
    private Double majorRatio;
    private Integer tuitionPerYear;
    private String provinceName;
    private String schoolNature;
    private List<String> riskFlags = Lists.newArrayList();
    /** reasonCodes + riskFlags + mustSubjects 的并集（review 限报/专项判据同源）。 */
    private List<String> riskTags = Lists.newArrayList();
    /** 该条目命中的覆盖要求 id：coverage:0、coverage:1…… */
    private List<String> matchedCoverageIds = Lists.newArrayList();
}
