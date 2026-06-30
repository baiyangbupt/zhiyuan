package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import org.junit.jupiter.api.Test;

import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class VolunteerBizServiceTest {

    @Test
    void shouldUseMajorCountWhenParsingLegacyMajorSourceWithSessionContext() {
        VolunteerBizService service = new VolunteerBizService();
        CreateSessionReq scoreDetail = buildScoreDetail(VolunteerModel.major, 96, 0, "aggressive");

        VolunteerRecommendListResponse response = service.parseVolunteerRecommendListResponse(
                buildLegacySourceJson("OTOO", 8374, 300, 4000, 120, 2500, 100, 1874, 80),
                scoreDetail);

        assertEquals(VolunteerModel.major, response.getBaseData().getVolunteerModel());
        assertTrue(Boolean.TRUE.equals(response.getMajorSchoolType()));
        assertEquals(Integer.valueOf(8374), response.getBaseData().getTotal_count());
        assertEquals(Integer.valueOf(96), response.getBaseData().getNeed_count());
        assertEquals(Integer.valueOf(38), response.getBaseData().getThree_target_count_map().get("sprints_count"));
        assertEquals(Integer.valueOf(28), response.getBaseData().getThree_target_count_map().get("safes_count"));
        assertEquals(Integer.valueOf(30), response.getBaseData().getThree_target_count_map().get("protects_count"));
    }

    @Test
    void shouldUseSchoolCountWhenParsingLegacyMajorGroupSourceWithSessionContext() {
        VolunteerBizService service = new VolunteerBizService();
        CreateSessionReq scoreDetail = buildScoreDetail(VolunteerModel.majorGroup, 6, 45, "aggressive");

        VolunteerRecommendListResponse response = service.parseVolunteerRecommendListResponse(
                buildLegacySourceJson("OTON", 8374, 210, 4000, 80, 2500, 70, 1874, 60),
                scoreDetail);

        assertEquals(VolunteerModel.majorGroup, response.getBaseData().getVolunteerModel());
        assertFalse(Boolean.TRUE.equals(response.getMajorSchoolType()));
        assertEquals(Integer.valueOf(210), response.getBaseData().getTotal_count());
        assertEquals(Integer.valueOf(45), response.getBaseData().getNeed_count());
        assertEquals(Integer.valueOf(18), response.getBaseData().getThree_target_count_map().get("sprints_count"));
        assertEquals(Integer.valueOf(13), response.getBaseData().getThree_target_count_map().get("safes_count"));
        assertEquals(Integer.valueOf(14), response.getBaseData().getThree_target_count_map().get("protects_count"));
    }

    private CreateSessionReq buildScoreDetail(VolunteerModel model,
                                              Integer majorCount,
                                              Integer schoolCount,
                                              String strategyCode) {
        CreateSessionReq scoreDetail = new CreateSessionReq();
        scoreDetail.setVolunteerModel(model);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setMajorCount(majorCount);
        volunteerCount.setSchoolCount(schoolCount);
        scoreDetail.setVolunteerCount(volunteerCount);
        CreateSessionReq.StrategyType strategyType = new CreateSessionReq.StrategyType();
        strategyType.setCode(strategyCode);
        scoreDetail.setStrategyType(strategyType);
        return scoreDetail;
    }

    private String buildLegacySourceJson(String applyType,
                                         Integer majorTotal,
                                         Integer schoolTotal,
                                         Integer majorSprint,
                                         Integer schoolSprint,
                                         Integer majorSafe,
                                         Integer schoolSafe,
                                         Integer majorProtect,
                                         Integer schoolProtect) {
        VolunteerDataDTO source = new VolunteerDataDTO();
        ProgramPageDTO.ProgramModel model = new ProgramPageDTO.ProgramModel();
        model.setMajorTotalNum(majorTotal);
        model.setSchoolTotalNum(schoolTotal);
        model.setMajorSprintNum(majorSprint);
        model.setSchoolSprintNum(schoolSprint);
        model.setMajorSafeNum(majorSafe);
        model.setSchoolSafeNum(schoolSafe);
        model.setMajorProtectNum(majorProtect);
        model.setSchoolProtectNum(schoolProtect);
        source.setModel(model);

        ProgramPageDTO.Type type = new ProgramPageDTO.Type();
        type.setCode(applyType);
        source.setType(type);

        ProgramPageDTO.SchoolDetail detail = new ProgramPageDTO.SchoolDetail();
        detail.setPlanSchoolDataId("ps1");
        detail.setSchoolId("s1");
        detail.setSchoolUnitName("School A");
        detail.setEnrollRatio("50");
        detail.setVolunteerLevel(type("SPRINT", "sprint"));
        detail.setPlanMajorDataId("pm1");
        detail.setMajorId("m1");
        detail.setMajorUnitName("Major A");
        detail.setMajorUnitCode("01");
        source.setDetailList(Collections.singletonList(detail));
        return JSON.toJSONString(source);
    }

    private ProgramPageDTO.Type type(String code, String desc) {
        ProgramPageDTO.Type type = new ProgramPageDTO.Type();
        type.setCode(code);
        type.setDesc(desc);
        return type;
    }
}
