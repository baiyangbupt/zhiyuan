package com.ytell.zhiyuan.service;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.res.UserInfoByTokenRes;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.when;

class GaotuServiceTest {

    @Test
    void shouldReturnReadableMessageWhenSubjectInfoMissing() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = new GaotuService();
        ReflectionTestUtils.setField(gaotuService, "gaotuClient", gaotuClient);

        ResponseDTO<UserInfoByTokenRes> response = new ResponseDTO<>();
        response.setCode(110);
        response.setMsg("\u7528\u6237\u9009\u79d1\u4fe1\u606f\u4e0d\u5b58\u5728");
        when(gaotuClient.getUserInfoByToken("token-a")).thenReturn(response);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.getUserInfoByToken("token-a"));

        assertEquals(110, exception.getStatus());
        assertEquals("\u8bf7\u5728\u9996\u9875\u5b8c\u5584\u9ad8\u8003\u7701\u4efd\u548c\u9009\u79d1\u4fe1\u606f\u540e\u518d\u8fdb\u5165AI\u667a\u80fd\u586b\u62a5", exception.getMessage());
    }
}
