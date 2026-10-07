package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.CandidateCompareReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateComparisonDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.ComparisonEntityDTO;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 按 ID 的候选比较：**值从会话候选池真实载入**，不是一个"仅构造数据"的空壳。
 *
 * <p>分工：{@link CandidateComparisonService} 只做口径判定与成形（值由调用方给）；
 * 这一层回答的是"值从哪来"——模型给出 2–5 个候选 `entityId`（= volunteerId，
 * 来自候选预览），这里把候选池里**真实存在的那几行**取出来，逐维度填进去，
 * 再交给比较服务成形。模型凭记忆填数字这条路必须堵死：比较表里的每个数都要
 * 在候选池里有对应的一行。</p>
 *
 * <p>三条纪律：</p>
 * <ol>
 *   <li><b>只读</b>：载入走 {@link CandidatePreviewService#loadReadOnlyCandidatePool}
 *       （不 savePlanningState、不 bump version）——比较不改被比较的东西；</li>
 *   <li><b>找不到就如实说</b>：ID 在候选池里不存在时进
 *       {@code entity_not_found:<id>} limitations，**不静默丢**；丢一个而返回 N-1 列的
 *       矩阵，读者会以为表里就是他要比的那几个；</li>
 *   <li><b>不可用就是不可用</b>：口径字段（年份/省份/批次/招生模式/率单位）取自会话，
 *       缺哪项哪项不填——比较服务会把相关数值列整列标不可比，而不是拿"默认口径"顶上去。</li>
 * </ol>
 */
@Service
public class CandidateCompareService {

    /** 找不到的 ID 逐条如实列出（前缀 + 原样 id）。 */
    public static final String LIMITATION_ENTITY_NOT_FOUND_PREFIX = "entity_not_found:";

    /** 载入后能比的实体不足 2 个：不是比较，如实说，不硬凑。 */
    public static final String LIMITATION_ENTITY_COUNT_INVALID = "comparison_entity_count_invalid";

    /** 空白 ID（""/"  "）被丢弃时如实标注。 */
    public static final String LIMITATION_BLANK_ENTITY_ID = "entity_id_blank_ignored";

    /** 值来自会话候选池的候选行；进每个单元格的 source 前缀。 */
    static final String VALUE_SOURCE = "candidatePool";

    /**
     * 率的单位。候选池的录取率来自上游的百分数串（`"85%"` → 85.0），
     * 单位是 percent——与分数线那条链路的 `score` 不是一个口径。
     */
    static final String RATE_UNIT_PERCENT = "percent";

    @Autowired
    private CandidatePreviewService candidatePreviewService;
    @Autowired
    private CandidateComparisonService candidateComparisonService;

    public CandidateComparisonDTO compare(Long tenantId, Long chatSessionId, CandidateCompareReq req) {
        CandidateCompareReq safeReq = req == null ? new CandidateCompareReq() : req;
        List<String> dimensions = CandidateComparisonService.resolveDimensions(safeReq.getDimensions());
        List<String> entityIds = new ArrayList<String>();
        boolean blankIdDropped = false;
        if (safeReq.getEntityIds() != null) {
            for (String value : safeReq.getEntityIds()) {
                String id = trimToNull(value);
                if (id == null) {
                    blankIdDropped = true;
                    continue;
                }
                entityIds.add(id);
            }
        }
        if (entityIds.size() < CandidateComparisonService.MIN_ENTITIES
                || entityIds.size() > CandidateComparisonService.MAX_ENTITIES) {
            throw new BusinessException(400, "comparison_entity_count_invalid");
        }

        CandidatePreviewService.ReadOnlyCandidatePool pool =
                candidatePreviewService.loadReadOnlyCandidatePool(tenantId, chatSessionId);
        List<String> limitations = new ArrayList<String>(pool.limitations);
        if (blankIdDropped) {
            limitations.add(LIMITATION_BLANK_ENTITY_ID);
        }
        if (pool.items == null || pool.items.isEmpty()) {
            // 与预览同一口径：来源不可用（FINISHED 会话 / 无志愿文件 / 空池）如实报，不 500。
            if (!limitations.contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE)) {
                limitations.add(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE);
            }
            return emptyResult(dimensions, limitations);
        }

        Map<String, CandidateItemDTO> candidatesById = indexByVolunteerId(pool.items);
        List<ComparisonEntityDTO> entities = new ArrayList<ComparisonEntityDTO>();
        for (String entityId : entityIds) {
            CandidateItemDTO candidate = candidatesById.get(entityId);
            if (candidate == null) {
                limitations.add(LIMITATION_ENTITY_NOT_FOUND_PREFIX + entityId);
                continue;
            }
            entities.add(toComparisonEntity(candidate, pool.response));
        }
        if (entities.size() < CandidateComparisonService.MIN_ENTITIES) {
            // 找到的不够两个：不能硬比。返回"为什么没得比"，而不是一张看着像结果的空表。
            limitations.add(LIMITATION_ENTITY_COUNT_INVALID);
            CandidateComparisonDTO result = emptyResult(dimensions, limitations);
            result.setEntities(entities);
            return result;
        }

        // 口径字段取自会话（同一次请求的实体共用同一口径身份）；比较服务负责
        // "这些值能不能放在一张表里比"的判定——缺口径就整列不可比，不默认同口径。
        CandidateComparisonDTO result = candidateComparisonService.compare(entities, dimensions);
        List<String> merged = new ArrayList<String>(limitations);
        merged.addAll(result.getLimitations());
        result.setLimitations(merged);
        return result;
    }

    /** 候选池行按 volunteerId 索引；同 id 多行时**保留第一行**（与预览的实体语义一致）。 */
    private Map<String, CandidateItemDTO> indexByVolunteerId(List<CandidateItemDTO> items) {
        Map<String, CandidateItemDTO> index = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO item : items) {
            String id = Strings.isNullOrEmpty(item.getVolunteerId()) ? null : item.getVolunteerId().trim();
            if (id == null || index.containsKey(id)) {
                continue;
            }
            index.put(id, item);
        }
        return index;
    }

    private ComparisonEntityDTO toComparisonEntity(CandidateItemDTO candidate,
                                                   VolunteerRecommendListResponse response) {
        ComparisonEntityDTO entity = new ComparisonEntityDTO();
        entity.setEntityId(candidate.getVolunteerId());
        entity.setSchoolId(candidate.getSchoolId());
        entity.setSchoolName(resolveSchoolName(candidate));
        entity.setMajorId(candidate.getMajorId());
        entity.setMajorName(candidate.getMajorName());
        entity.setCityName(candidate.getCityName());

        // 口径身份：会话级的五个字段。取不到就留空——"不知道口径是否相同"不等于"相同"。
        CreateSessionReq scoreDetail = response == null ? null : response.getUserScoreDetail();
        if (scoreDetail != null) {
            entity.setAdmissionYear(scoreDetail.getExamYear());
            entity.setAreaId(scoreDetail.getProvince() == null ? null : trimToNull(scoreDetail.getProvince().getCode()));
            entity.setBatch(scoreDetail.getBatch() == null ? null : trimToNull(scoreDetail.getBatch().getCode()));
        }
        entity.setAdmissionMode(resolveAdmissionMode(scoreDetail, response));
        entity.setRateUnit(RATE_UNIT_PERCENT);

        // 有真实来源的维度值（候选池行）：录取率/学校率/匹配分/计划数/学费；其余维度
        // 在比较服务里没有取数入口，不给值（宁可缺失，也不补零或造数）。
        entity.setAdmissionRatio(candidate.getAdmissionRatio());
        entity.setSchoolEnrollRatio(candidate.getSchoolEnrollRatio());
        entity.setFinalScore(candidate.getFinalScore());
        entity.setPlanNum(candidate.getPlanNum());
        entity.setTuitionPerYear(candidate.getTuitionPerYear());
        entity.setMustSubjects(candidate.getMustSubjects());
        entity.setRiskFlags(candidate.getRiskFlags());
        entity.setValueSource(VALUE_SOURCE);
        return entity;
    }

    /**
     * 招生模式：会话的填报模式（`major` 专业+院校 / `majorGroup` 专业组）。
     * 学校级与专业组级不能并排——它们的招生单元不同，混在一张表里等于拿两个口径的数比大小。
     */
    private String resolveAdmissionMode(CreateSessionReq scoreDetail, VolunteerRecommendListResponse response) {
        VolunteerModel model = scoreDetail == null ? null : scoreDetail.getVolunteerModel();
        if (model == null && response != null && response.getBaseData() != null) {
            model = response.getBaseData().getVolunteerModel();
        }
        return model == null ? null : trimToNull(model.getCode());
    }

    private String resolveSchoolName(CandidateItemDTO candidate) {
        return Strings.isNullOrEmpty(candidate.getDisplaySchoolName())
                ? candidate.getSchoolName() : candidate.getDisplaySchoolName();
    }

    /** 空矩阵：没有值、没有格子，只有"为什么没有"。 */
    private CandidateComparisonDTO emptyResult(List<String> dimensions, List<String> limitations) {
        CandidateComparisonDTO result = new CandidateComparisonDTO();
        result.setDimensions(new ArrayList<String>(dimensions));
        result.setLimitations(new ArrayList<String>(limitations));
        return result;
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
