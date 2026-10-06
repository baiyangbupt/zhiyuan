package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.gaotu.BatchDataResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.SubjectPolicyResponseDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@link ScoreCatalogService#provinceDefaultsOrNull}：一次策略查询里能推导出的补录缺省。
 *
 * <p>科类只取"该省唯一"（浙江 N/综合）；多科类省份（江苏 WL/LS）不回科类、不替用户挑，
 * 但 prepareType 照旧要能取到（前端口径：`policy.prepareType.code` 就是批次线与建会话的
 * 填报类型）。上游不可用时一律 null——调用方保持各自原兜底（110 / VOLUNTEER），不放宽。</p>
 */
public class ScoreCatalogServiceProvinceDefaultsTest {

    private ScoreCatalogService service;
    private GaotuClient gaotuClient;

    @BeforeEach
    void setUp() {
        service = new ScoreCatalogService();
        gaotuClient = mock(GaotuClient.class);
        ReflectionTestUtils.setField(service, "gaotuClient", gaotuClient);
    }

    @Test
    void singleSubjectTypeProvinceYieldsBothDefaults() {
        when(gaotuClient.getSubjectPolicy("330000")).thenReturn(policy(
                Lists.newArrayList(subjectType("N", "综合")), type("PREDICT", "模拟填报")));

        ScoreCatalogService.ProvinceDefaults defaults = service.provinceDefaultsOrNull("330000");

        assertEquals("N", defaults.getSubjectType().getCode());
        assertEquals("综合", defaults.getSubjectType().getDesc());
        assertEquals("PREDICT", defaults.getPrepareType().getCode());
        assertEquals("模拟填报", defaults.getPrepareType().getDesc());
    }

    @Test
    void multiSubjectTypeProvinceYieldsPrepareTypeOnly() {
        when(gaotuClient.getSubjectPolicy("320000")).thenReturn(policy(
                Lists.newArrayList(subjectType("WL", "物理"), subjectType("LS", "历史")),
                type("VOLUNTEER", "智能填报")));

        ScoreCatalogService.ProvinceDefaults defaults = service.provinceDefaultsOrNull("320000");

        assertNull(defaults.getSubjectType(), "多科类不替用户挑：科类缺省必须为空");
        assertEquals("VOLUNTEER", defaults.getPrepareType().getCode());
    }

    @Test
    void upstreamFailureYieldsNullInsteadOfBlowingUpThePreview() {
        when(gaotuClient.getSubjectPolicy("330000")).thenReturn(null);

        assertNull(service.provinceDefaultsOrNull("330000"),
                "上游挂了照旧回 null：补录按原校验/兜底走，不能因此 500");
    }

    @Test
    void blankProvinceYieldsNullWithoutAnUpstreamCall() {
        assertNull(service.provinceDefaultsOrNull(" "));
    }

    private ResponseDTO<SubjectPolicyResponseDTO> policy(java.util.List<SubjectPolicyResponseDTO.SubjectTypeOption> types,
                                                         BatchDataResponseDTO.TypeInfo prepareType) {
        SubjectPolicyResponseDTO data = new SubjectPolicyResponseDTO();
        data.setSubjectTypeList(types);
        data.setPrepareType(prepareType);
        ResponseDTO<SubjectPolicyResponseDTO> response = new ResponseDTO<SubjectPolicyResponseDTO>();
        response.setCode(0);
        response.setMsg("ok");
        response.setData(data);
        return response;
    }

    private SubjectPolicyResponseDTO.SubjectTypeOption subjectType(String code, String desc) {
        SubjectPolicyResponseDTO.SubjectTypeOption option = new SubjectPolicyResponseDTO.SubjectTypeOption();
        option.setCode(code);
        option.setDesc(desc);
        return option;
    }

    private BatchDataResponseDTO.TypeInfo type(String code, String desc) {
        BatchDataResponseDTO.TypeInfo info = new BatchDataResponseDTO.TypeInfo();
        info.setCode(code);
        info.setDesc(desc);
        return info;
    }
}
