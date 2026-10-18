package com.ytell.zhiyuan.model.dto.planning;

import com.alibaba.fastjson.annotation.JSONField;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * J5.1 候选快照中的单个实体事实。
 *
 * <p>unit 模式下 entity 是专业组，{@link #volunteerIds} 是组内专业；
 * volunteer 模式下 entity 是单个志愿。{@link #rawCandidates} 只供服务端
 * 求解/匹配使用，不序列化到 API。</p>
 */
@Data
public class CandidateFactDTO {
    private String entityId;
    private List<String> volunteerIds = Lists.newArrayList();
    private String unitId;
    private String schoolId;
    private String majorId;
    private String provinceId;
    private String provinceName;
    private String cityId;
    private String cityName;
    private String schoolLevel;
    private String schoolNature;
    private String schoolCategory;
    private String majorCategoryId;
    private String majorSubCategoryId;
    private Integer tuitionPerYear;
    private Double admissionRatio;
    private Double schoolEnrollRatio;
    private Double intentScore;
    private Double finalScore;
    private Double futureDevelopmentScore;
    private Integer schoolRank;
    private List<String> riskFlags = Lists.newArrayList();

    /** canonical key: sprint | stable | protect | unknown */
    private String tier;
    private String tierSource;

    private Boolean eligible = false;
    private List<String> eligibilityReasonCodes = Lists.newArrayList();
    private Boolean compensationSafe = false;
    private Boolean unitAllSafe = false;
    private Boolean priorityMatched = false;

    private Boolean current = false;
    private Boolean locked = false;
    private Boolean pinned = false;
    private Integer stableOrder;

    /** 内部效用分量，0..100；不序列化到 API。 */
    @JSONField(serialize = false)
    private Map<String, Integer> utilityComponents = Maps.newLinkedHashMap();
    @JSONField(serialize = false)
    private Integer utilityScore = 0;
    @JSONField(serialize = false)
    private Integer utilityCoverage = 0;

    /** working_plan | candidate_pool；内部使用。 */
    @JSONField(serialize = false)
    private String source;

    /** unit 模式保留组内原始专业，供 coverage/eligibility 复用既有谓词。 */
    @JSONField(serialize = false)
    private List<CandidateItemDTO> rawCandidates = Lists.newArrayList();
}
