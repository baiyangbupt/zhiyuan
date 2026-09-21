package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.req.QueryPlanMajorDataReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.PlanMajorDataRes;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

public class AdmissionSourceServiceTest {

    private AdmissionSourceService service;
    private GaotuClient gaotuClient;

    @BeforeEach
    void setUp() {
        service = new AdmissionSourceService();
        gaotuClient = Mockito.mock(GaotuClient.class);
        ReflectionTestUtils.setField(service, "gaotuClient", gaotuClient);
    }

    @Test
    void latestPublishedYearIsTakenFromUpstreamNotFromOurOwnInference() {
        // 上游给的是"哪些年份有数据"，本仓只做"最近 ≤ 请求年"的选择，
        // 不推断展示年（预测口径的 −1 规则在上游 PlanDisplayYearUtil 里）。
        assertEquals(2025, AdmissionSourceService.latestPublishedYear(2026,
                Arrays.asList("2024", "2025")));
        assertEquals(2025, AdmissionSourceService.latestPublishedYear(2025,
                Arrays.asList("2024", "2025")));
    }

    @Test
    void aRequestedYearOlderThanEverythingIsRefused() {
        // 全部年份都比请求的新：请求本身有问题，不能悄悄取最近一条。
        BusinessException ex = assertThrows(BusinessException.class,
                () -> AdmissionSourceService.latestPublishedYear(2020, Arrays.asList("2024", "2025")));
        assertEquals(404, ex.getStatus());
    }

    @Test
    void noUpstreamYearsMeansTheCapabilityIsUnavailable() {
        assertEquals(404, assertThrows(BusinessException.class,
                () -> AdmissionSourceService.latestPublishedYear(2026, new ArrayList<String>())).getStatus());
        assertEquals(404, assertThrows(BusinessException.class,
                () -> AdmissionSourceService.latestPublishedYear(2026, null)).getStatus());
    }

    @Test
    void nonNumericYearsAreIgnoredRatherThanCrashing() {
        assertEquals(2025, AdmissionSourceService.latestPublishedYear(2026,
                Arrays.asList("2024", "2025", "全部", "")));
    }

    @Test
    void emptyUpstreamResultIsReportedAsEmptyNotAsZeroPlan() {
        when(gaotuClient.queryPlanMajorData(any(QueryPlanMajorDataReq.class), any(EvidenceScope.class)))
                .thenReturn(responseWith(new ArrayList<PlanMajorDataRes>()));
        QueryPlanMajorDataReq request = new QueryPlanMajorDataReq();
        request.setSchoolId("s1");

        Map<String, Object> result = service.listEnrollment(request, 20, EvidenceScope.none());

        // "没有行"和"计划为 0"是两件事：前者去核对年份/省份，后者不用。
        assertEquals("empty", result.get("status"));
        assertTrue(((List<?>) result.get("limitations")).contains("enrollment_no_rows_for_scope"));
    }

    @Test
    void pageSizeIsCapped() {
        List<PlanMajorDataRes> rows = new ArrayList<PlanMajorDataRes>();
        for (int index = 0; index < 80; index++) {
            rows.add(new PlanMajorDataRes());
        }
        when(gaotuClient.queryPlanMajorData(any(QueryPlanMajorDataReq.class), any(EvidenceScope.class)))
                .thenReturn(responseWith(rows));
        QueryPlanMajorDataReq request = new QueryPlanMajorDataReq();
        request.setSchoolId("s1");

        Map<String, Object> result = service.listEnrollment(request, 999, EvidenceScope.none());

        assertEquals(AdmissionSourceService.MAX_PAGE_SIZE, ((List<?>) result.get("data")).size());
        assertEquals(80, result.get("total"));
    }

    @Test
    void aMissingSchoolIsRefusedBeforeCallingUpstream() {
        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.listEnrollment(new QueryPlanMajorDataReq(), 20, EvidenceScope.none()));

        assertEquals(400, ex.getStatus());
        Mockito.verify(gaotuClient, Mockito.never())
                .queryPlanMajorData(any(QueryPlanMajorDataReq.class), any(EvidenceScope.class));
    }

    private static ResponseDTO<List<PlanMajorDataRes>> responseWith(List<PlanMajorDataRes> rows) {
        ResponseDTO<List<PlanMajorDataRes>> response = new ResponseDTO<List<PlanMajorDataRes>>();
        response.setCode(0);
        response.setData(rows);
        return response;
    }

    @Test
    void policyAlwaysDeclaresThatTheSourceMayBePlaceholderText() {
        com.ytell.zhiyuan.model.dto.gaotu.res.SchoolRuleRes rule = new com.ytell.zhiyuan.model.dto.gaotu.res.SchoolRuleRes();
        rule.setTitle("2026招生章程");
        rule.setContent("正在更新中");
        com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO<com.ytell.zhiyuan.model.dto.gaotu.res.SchoolRuleRes> response =
                new com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO<com.ytell.zhiyuan.model.dto.gaotu.res.SchoolRuleRes>();
        response.setCode(0);
        response.setData(rule);
        when(gaotuClient.getSchoolRule(1L)).thenReturn(response);

        Map<String, Object> result = service.getPolicy(1L);

        // 上游在"该校没规则"时回的就是占位文案，且没有标志位。
        // 所以这两条 limitations 必须**无条件**带上，不能只在疑似时加。
        List<?> limitations = (List<?>) result.get("limitations");
        assertTrue(limitations.contains("policy_source_is_display_text_not_verbatim"));
        assertTrue(limitations.contains("policy_placeholder_content_possible"));
        // 不签发证据：它不是取数结果。
        assertEquals(0, ((List<?>) result.get("evidence")).size());
    }

    @Test
    void anEmptyRuleIsReportedAsEmptyNotAsAnEmptyCharter() {
        com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO<com.ytell.zhiyuan.model.dto.gaotu.res.SchoolRuleRes> response =
                new com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO<com.ytell.zhiyuan.model.dto.gaotu.res.SchoolRuleRes>();
        response.setCode(0);
        response.setData(null);
        when(gaotuClient.getSchoolRule(2L)).thenReturn(response);

        Map<String, Object> result = service.getPolicy(2L);

        assertEquals("empty", result.get("status"));
        assertEquals(null, result.get("data"));
    }
}
