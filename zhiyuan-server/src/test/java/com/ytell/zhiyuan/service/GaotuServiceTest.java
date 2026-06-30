package com.ytell.zhiyuan.service;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.req.ProgramPageReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.RecommendNumReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.UserInfoByTokenRes;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.net.SocketTimeoutException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.when;

class GaotuServiceTest {

    @Test
    void shouldReturnReadableMessageWhenSubjectInfoMissing() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);

        ResponseDTO<UserInfoByTokenRes> response = new ResponseDTO<>();
        response.setCode(110);
        response.setMsg("\u7528\u6237\u9009\u79d1\u4fe1\u606f\u4e0d\u5b58\u5728");
        when(gaotuClient.getUserInfoByToken("token-a")).thenReturn(response);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.getUserInfoByToken("token-a"));

        assertEquals(110, exception.getStatus());
        assertEquals("\u8bf7\u5728\u9996\u9875\u5b8c\u5584\u9ad8\u8003\u7701\u4efd\u548c\u9009\u79d1\u4fe1\u606f\u540e\u518d\u8fdb\u5165AI\u667a\u80fd\u586b\u62a5", exception.getMessage());
    }

    @Test
    void shouldReturnReadableMessageWhenVolunteerFullDataTimeout() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ProgramPageReq req = validProgramPageReq();

        when(gaotuClient.getProgramFullList(req)).thenThrow(volunteerDataTimeout());

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.queryAllProgramData(req));

        assertEquals(110, exception.getStatus());
        assertEquals("\u5fd7\u613f\u6570\u636e\u83b7\u53d6\u8d85\u65f6", exception.getMessage());
    }

    @Test
    void shouldReturnReadableMessageWhenRecommendProgramNumTimeout() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        RecommendNumReq req = new RecommendNumReq();

        when(gaotuClient.getRecommendProgramNum(req)).thenThrow(volunteerDataTimeout());

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.getRecommendProgramNum(req));

        assertEquals(110, exception.getStatus());
        assertEquals("\u5fd7\u613f\u6570\u636e\u83b7\u53d6\u8d85\u65f6", exception.getMessage());
    }

    @Test
    void shouldNotMaskVolunteerProgramTimeoutDuringRetry() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ProgramPageReq req = validProgramPageReq();

        when(gaotuClient.getProgramList(req)).thenThrow(volunteerDataTimeout());

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.queryAndSaveProgram(req, new RecommendNumResponse()));

        assertEquals(110, exception.getStatus());
        assertEquals("\u5fd7\u613f\u6570\u636e\u83b7\u53d6\u8d85\u65f6", exception.getMessage());
        Mockito.verify(gaotuClient, Mockito.times(1)).getProgramList(req);
    }

    private GaotuService serviceWithClient(GaotuClient gaotuClient) {
        GaotuService gaotuService = new GaotuService();
        ReflectionTestUtils.setField(gaotuService, "gaotuClient", gaotuClient);
        return gaotuService;
    }

    private ProgramPageReq validProgramPageReq() {
        ProgramPageReq req = new ProgramPageReq();
        req.setAreaId("110000");
        req.setPrepareType("PREDICT");
        return req;
    }

    private RuntimeException volunteerDataTimeout() {
        return new RuntimeException("invoke HTTP error", new SocketTimeoutException("Read timed out"));
    }
}
