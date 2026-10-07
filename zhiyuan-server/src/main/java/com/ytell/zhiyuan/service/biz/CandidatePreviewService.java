package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePreviewReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePreviewRes;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 候选预览（只读纵切）。
 *
 * <p>存在的理由：Codex 线的只读工具里**没有任何一条能拿到候选池**——模型只能比较、
 * 查历史，看不到"这个学生现在有哪些可报候选"。这里把 Java 侧真实存在的候选流水线
 * （推荐 → 排序 → 成形）以**只读**方式暴露出来。</p>
 *
 * <p>三条纪律（每条都是评审点）：</p>
 * <ol>
 *   <li><b>不落盘</b>：主路径只调 {@code recommendVolunteerList(tenant, session, false, false)}
 *       （`saveToFile=false` 不走 OSS），成形复用 {@link PlanningStateService}
 *       的包内方法 {@code buildCandidatePoolStateFromResponse}（不含 savePlanningState /
 *       version 自增），**不**经过 {@code queryCandidatePool}——后者会
 *       {@code refreshRecommendationOverlay → savePlanningState}。规划版本因此不变。</li>
 *   <li><b>只见一页</b>：{@link #MAX_PAGE_SIZE} 是硬上限，全量候选留在服务器，
 *       {@code total} 给的是过滤后的全量条数。</li>
 *   <li><b>缺来源不 500</b>：FINISHED 会话与无志愿文件的会话返回
 *       {@code limitations:[candidate_source_unavailable]}，而不是抛错。</li>
 * </ol>
 */
@Slf4j
@Service
public class CandidatePreviewService {

    /** 预览一次最多带回的候选条数。**硬上限**：超过的请求被截断，不报错。 */
    public static final int MAX_PAGE_SIZE = 20;

    /** 候选来源不可用（FINISHED 会话 / 无志愿文件 / 成形失败）。 */
    public static final String LIMITATION_SOURCE_UNAVAILABLE = "candidate_source_unavailable";

    /** 本切片不支持的过滤维度会如实报出来，而不是静默丢掉。 */
    public static final String LIMITATION_FILTER_UNSUPPORTED_PREFIX = "filter_unsupported:";

    @Autowired
    private VolunteerBizService volunteerBizService;
    @Autowired
    private PlanningStateService planningStateService;
    @Autowired
    private VolunteerDataProvider volunteerDataProvider;

    /**
     * 只读候选池载入结果。{@code items} 为 **null** 表示来源不可用（原因已进
     * {@code limitations}）；非 null 时可能是空列表（流水线跑通但一条候选都没有）。
     */
    static class ReadOnlyCandidatePool {
        PlanningStateDTO state;
        VolunteerRecommendListResponse response;
        List<CandidateItemDTO> items;
        final List<String> limitations = Lists.newArrayList();
    }

    /**
     * 只读载入会话候选池的行（推荐 → 成形），**不落盘**：不 savePlanningState、不 bump version。
     *
     * <p>从 {@link #preview} 抽出的可复用包内方法（逻辑一字未改）：按 ID 载入候选行做比较
     * （{@link CandidateCompareService}）需要同一份载入语义——不共用的话，两条链路迟早
     * 一条在写、一条在读，而"比较看到了什么"就不再等于"预览看到了什么"。</p>
     */
    ReadOnlyCandidatePool loadReadOnlyCandidatePool(Long tenantId, Long chatSessionId) {
        ReadOnlyCandidatePool loaded = new ReadOnlyCandidatePool();
        // 只读加载：不能用 loadPlanningState（它会为 legacy 会话懒导入并 savePlanningState），
        // 也不能用 getPlanningState/queryCandidatePool（后者会刷新 overlay 落盘）。
        loaded.state = planningStateService.loadPlanningStateReadOnly(chatSessionId);

        ChatSession session = null;
        try {
            session = volunteerDataProvider.getChatSession(chatSessionId);
        } catch (Exception ex) {
            log.warn("candidatePool session load failed tenantId={} chatSessionId={}", tenantId, chatSessionId, ex);
        }
        if (session != null && SessionStatus.FINISHED.equals(session.getSessionStatus())) {
            // 已提交会话不再重算：它的候选来源是"当时提交的那份"，预览/比较面不把旧提交当现行候选。
            loaded.limitations.add(LIMITATION_SOURCE_UNAVAILABLE);
            return loaded;
        }

        VolunteerRecommendListResponse response;
        try {
            response = volunteerBizService.recommendVolunteerList(tenantId, chatSessionId, false, false);
        } catch (Exception ex) {
            // 无志愿文件就是这样落地的（本地缺失 → OSS 下载失败 → 业务异常）：如实报来源不可用，不 500。
            log.warn("candidatePool recommend unavailable tenantId={} chatSessionId={}: {}",
                    tenantId, chatSessionId, ex.getMessage());
            loaded.limitations.add(LIMITATION_SOURCE_UNAVAILABLE);
            return loaded;
        }
        if (response == null) {
            loaded.limitations.add(LIMITATION_SOURCE_UNAVAILABLE);
            return loaded;
        }
        loaded.response = response;

        try {
            CandidatePoolStateDTO poolState = planningStateService.buildCandidatePoolStateFromResponse(
                    chatSessionId, loaded.state, response);
            loaded.items = poolState == null || poolState.getItems() == null
                    ? Lists.newArrayList() : poolState.getItems();
        } catch (Exception ex) {
            log.warn("candidatePool shaping failed tenantId={} chatSessionId={}", tenantId, chatSessionId, ex);
            loaded.limitations.add(LIMITATION_SOURCE_UNAVAILABLE);
            return loaded;
        }
        return loaded;
    }

    public CandidatePreviewRes preview(Long tenantId, Long chatSessionId, CandidatePreviewReq req) {
        CandidatePreviewReq safeReq = req == null ? new CandidatePreviewReq() : req;
        CandidatePreviewRes res = new CandidatePreviewRes();
        res.setPage(resolvePage(safeReq.getPage()));
        res.setPageSize(resolvePageSize(safeReq.getPageSize()));

        ReadOnlyCandidatePool loaded = loadReadOnlyCandidatePool(tenantId, chatSessionId);
        res.setProfileVersion(loaded.state == null ? null : loaded.state.getVersion());
        res.setDataVersion(resolveDataVersion(loaded.state));
        res.getLimitations().addAll(loaded.limitations);
        if (loaded.items == null) {
            return res;
        }
        List<CandidateItemDTO> all = loaded.items;

        List<CandidateItemDTO> filtered = applyFilters(all, safeReq.getFilters(), res.getLimitations());
        res.setTotal(filtered.size());
        int fromIndex = Math.min((res.getPage() - 1) * res.getPageSize(), filtered.size());
        int toIndex = Math.min(fromIndex + res.getPageSize(), filtered.size());
        for (CandidateItemDTO candidate : filtered.subList(fromIndex, toIndex)) {
            res.getItems().add(toPreviewItem(candidate));
        }
        if (all.isEmpty() && res.getLimitations().isEmpty()) {
            // 流水线跑通但一条候选都没有：与"文件缺失"同源，如实标注（不是 500）。
            res.getLimitations().add(LIMITATION_SOURCE_UNAVAILABLE);
        }
        return res;
    }

    private int resolvePage(Integer page) {
        return page == null || page < 1 ? 1 : page;
    }

    private int resolvePageSize(Integer pageSize) {
        int requested = pageSize == null || pageSize < 1 ? MAX_PAGE_SIZE : pageSize;
        return Math.min(requested, MAX_PAGE_SIZE);
    }

    private String resolveDataVersion(PlanningStateDTO state) {
        if (state == null || state.getDataFreshnessState() == null) {
            return null;
        }
        DataFreshnessStateDTO freshness = state.getDataFreshnessState();
        if (!Strings.isNullOrEmpty(freshness.getDataVersion())) {
            return freshness.getDataVersion();
        }
        if (!Strings.isNullOrEmpty(freshness.getSourceDataHash())) {
            return freshness.getSourceDataHash();
        }
        return null;
    }

    /**
     * 过滤只覆盖"结构里直接有的字段"：档位、省份、城市、院校名、专业名（正负向）。
     * 标签类过滤在候选池查询里走的是另一套聚合逻辑，本切片不搬——**报出来**而不是悄悄忽略。
     */
    private List<CandidateItemDTO> applyFilters(List<CandidateItemDTO> items,
                                                CandidatePoolQueryReq.Filters filters,
                                                List<String> limitations) {
        if (filters == null) {
            return items;
        }
        if (isNotEmpty(filters.getSchoolTags()) || isNotEmpty(filters.getNegativeSchoolTags())) {
            limitations.add(LIMITATION_FILTER_UNSUPPORTED_PREFIX + "schoolTags");
        }
        if (isNotEmpty(filters.getMajorTags()) || isNotEmpty(filters.getNegativeMajorTags())) {
            limitations.add(LIMITATION_FILTER_UNSUPPORTED_PREFIX + "majorTags");
        }
        return items.stream()
                .filter(item -> matchesTier(item, filters.getTiers()))
                .filter(item -> matchesPositiveNegative(item.getProvinceName(),
                        filters.getProvinceNames(), filters.getNegativeProvinceNames()))
                .filter(item -> matchesPositiveNegative(item.getCityName(),
                        filters.getCityNames(), filters.getNegativeCityNames()))
                .filter(item -> matchesPositiveNegative(resolveSchoolName(item),
                        filters.getSchoolKeywords(), filters.getNegativeSchoolKeywords()))
                .filter(item -> matchesPositiveNegative(item.getMajorName(),
                        filters.getMajorKeywords(), filters.getNegativeMajorKeywords()))
                .collect(Collectors.toList());
    }

    private boolean matchesTier(CandidateItemDTO item, List<String> tiers) {
        return !isNotEmpty(tiers) || tiers.contains(item.getTier());
    }

    private boolean matchesPositiveNegative(String value, List<String> positives, List<String> negatives) {
        boolean positiveMatched = !isNotEmpty(positives)
                || positives.stream().anyMatch(candidate -> containsIgnoreCase(value, candidate));
        boolean negativeMatched = isNotEmpty(negatives)
                && negatives.stream().anyMatch(candidate -> containsIgnoreCase(value, candidate));
        return positiveMatched && !negativeMatched;
    }

    private boolean containsIgnoreCase(String value, String keyword) {
        return value != null && keyword != null
                && value.toLowerCase().contains(keyword.toLowerCase());
    }

    private boolean isNotEmpty(List<String> values) {
        return values != null && !values.isEmpty();
    }

    private CandidatePreviewRes.Item toPreviewItem(CandidateItemDTO candidate) {
        CandidatePreviewRes.Item item = new CandidatePreviewRes.Item();
        item.setEntityId(candidate.getVolunteerId());
        item.setVolunteerId(candidate.getVolunteerId());
        item.setTier(candidate.getTier());
        item.setSchoolId(candidate.getSchoolId());
        item.setSchoolName(resolveSchoolName(candidate));
        item.setMajorId(candidate.getMajorId());
        item.setMajorName(candidate.getMajorName());
        item.setFinalScore(candidate.getFinalScore());
        item.setAdmissionRatio(candidate.getAdmissionRatio());
        item.setSchoolEnrollRatio(candidate.getSchoolEnrollRatio());
        item.setRankInTier(candidate.getRankInTier());
        item.setPlanNum(candidate.getPlanNum());
        item.setTuitionPerYear(candidate.getTuitionPerYear());
        item.setMustSubjects(defaultList(candidate.getMustSubjects()));
        item.setRiskFlags(defaultList(candidate.getRiskFlags()));
        item.setReasonCodes(defaultList(candidate.getReasonCodes()));
        return item;
    }

    private String resolveSchoolName(CandidateItemDTO candidate) {
        return Strings.isNullOrEmpty(candidate.getDisplaySchoolName())
                ? candidate.getSchoolName() : candidate.getDisplaySchoolName();
    }

    private List<String> defaultList(List<String> values) {
        return values == null ? Lists.newArrayList() : values;
    }
}
