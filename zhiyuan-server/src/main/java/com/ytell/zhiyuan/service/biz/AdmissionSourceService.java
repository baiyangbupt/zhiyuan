package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.gaotu.req.QueryPlanMajorDataReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.PlanMajorDataRes;
import com.ytell.zhiyuan.model.dto.gaotu.res.SchoolRuleRes;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/**
 * 年度招生计划查询。
 *
 * <p>数据在上游（`z_plan_school_data` / `z_plan_major_data`），经 `SchoolH5Controller`
 * 的免 token 端点取。**不走自建导入 catalog**——那条路径降级为兜底，
 * 因为"本仓没接"曾被误当成"上游没有"（见 `admission-sources-v1.md` 的勘误）。
 *
 * <p>三条边界：
 * <ul>
 *   <li><b>年份不自己算。</b> "最近已发布年份"问上游的筛选条件接口，
 *       而不是推断"表里最大的 year"。展示年口径（预测=数据年−1）在上游
 *       `PlanDisplayYearUtil` 里，本仓重算一遍必然与它不一致。</li>
 *   <li><b>不合成。</b> 上游没返回就是没有，不用别的数据顶替。</li>
 *   <li><b>分页有上限。</b> 默认 20、最大 50。</li>
 * </ul>
 */
@Service
public class AdmissionSourceService {

    private static final Logger log = LoggerFactory.getLogger(AdmissionSourceService.class);

    public static final int DEFAULT_PAGE_SIZE = 20;
    public static final int MAX_PAGE_SIZE = 50;

    @Autowired
    private GaotuClient gaotuClient;

    /**
     * 批量查询招生计划，按身份取数（入参不含分数）。
     */
    public Map<String, Object> listEnrollment(QueryPlanMajorDataReq request, Integer limit,
                                              EvidenceScope scope) {
        if (request == null || isBlank(request.getSchoolId())) {
            throw new BusinessException(400, "admission_source_school_required");
        }
        ResponseDTO<List<PlanMajorDataRes>> response = gaotuClient.queryPlanMajorData(request, scope);
        List<PlanMajorDataRes> rows = response == null || response.getData() == null
                ? Collections.<PlanMajorDataRes>emptyList()
                : response.getData();

        Map<String, Object> result = new LinkedHashMap<String, Object>();
        result.put("kind", "enrollment");
        result.put("status", rows.isEmpty() ? "empty" : "ok");
        result.put("data", page(rows, limit));
        result.put("total", rows.size());
        result.put("evidence", response == null ? Collections.emptyList() : response.getEvidence());
        List<String> limitations = new ArrayList<String>();
        if (rows.isEmpty()) {
            // 空既可能是"该年没发布"，也可能是"这所学校该省不投放"。
            // 两者都不该被说成"计划为 0"。
            limitations.add("enrollment_no_rows_for_scope");
        }
        result.put("limitations", limitations);
        return result;
    }

    /**
     * 从**上游给的**年份列表里取最近已发布年份。
     *
     * <p>入参来自上游筛选条件接口，不是本仓扫表推出来的。当年未发布时回上一年，
     * 由调用方在 limitations 里说明——不能把去年称作今年。
     */
    public static int latestPublishedYear(int requestedYear, List<String> upstreamYears) {
        TreeSet<Integer> years = new TreeSet<Integer>();
        for (String raw : upstreamYears == null ? Collections.<String>emptyList() : upstreamYears) {
            try {
                years.add(Integer.parseInt(String.valueOf(raw).trim()));
            } catch (NumberFormatException ignored) {
                // 年份不是数字的条目直接忽略：它们没法参与"最近"的比较。
            }
        }
        if (years.isEmpty()) {
            throw new BusinessException(404, "admission_year_unavailable");
        }
        Integer floor = years.floor(requestedYear);
        if (floor == null) {
            // 全部年份都比请求的新：请求本身有问题，不能悄悄取最近一条。
            throw new BusinessException(404, "admission_year_unavailable");
        }
        return floor;
    }

    /**
     * 查询学校招生章程。
     *
     * <p>**必须带上两条 limitations**，因为这条端点给的不是可靠原文：
     * 上游在该校没有规则时回的是配置的占位文案（默认"正在更新中"），
     * 而响应里没有标志位区分。B3 要求"以原文条款为依据，模型解释与原文并列"——
     * 拿占位文案当原文引用，学生看到的是"正在更新中"被当成章程条款。
     */
    public Map<String, Object> getPolicy(Long schoolId) {
        if (schoolId == null) {
            throw new BusinessException(400, "admission_source_school_required");
        }
        ResponseDTO<SchoolRuleRes> response = gaotuClient.getSchoolRule(schoolId);
        SchoolRuleRes rule = response == null ? null : response.getData();

        Map<String, Object> result = new LinkedHashMap<String, Object>();
        result.put("kind", "policy");
        boolean hasContent = rule != null && !isBlank(rule.getContent());
        result.put("status", hasContent ? "ok" : "empty");
        if (hasContent) {
            Map<String, Object> data = new LinkedHashMap<String, Object>();
            data.put("schoolId", String.valueOf(schoolId));
            data.put("title", rule.getTitle());
            data.put("content", rule.getContent());
            result.put("data", data);
        } else {
            result.put("data", null);
        }
        List<String> limitations = new ArrayList<String>();
        // 两条都与"这条内容能不能当原文"直接相关，不能省。
        limitations.add("policy_source_is_display_text_not_verbatim");
        limitations.add("policy_placeholder_content_possible");
        result.put("limitations", limitations);
        // 不签发证据：它不是取数结果。给它签证据等于把"查过数仓"的权威性
        // 借给一段可能只是占位文案的文本。
        result.put("evidence", Collections.emptyList());
        return result;
    }

    private <T> List<T> page(List<T> rows, Integer limit) {
        int size = limit == null || limit <= 0 ? DEFAULT_PAGE_SIZE : Math.min(limit, MAX_PAGE_SIZE);
        return new ArrayList<T>(rows.subList(0, Math.min(size, rows.size())));
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
