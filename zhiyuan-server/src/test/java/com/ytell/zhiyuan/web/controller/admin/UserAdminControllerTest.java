package com.ytell.zhiyuan.web.controller.admin;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.UserCredentialMapper;
import com.ytell.zhiyuan.model.dto.LimitSettingsOb;
import com.ytell.zhiyuan.model.dto.gaotu.res.UserRightsByUserIdRes;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.LoginType;
import com.ytell.zhiyuan.model.enums.UserLevel;
import com.ytell.zhiyuan.model.vo.UserVO;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.biz.UserBizService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class UserAdminControllerTest {

    private UserAdminController controller;
    private UserCredentialMapper userCredentialMapper;
    private UserBizService userBizService;
    private GaotuService gaotuService;

    @BeforeEach
    void setUp() {
        controller = new UserAdminController();
        userCredentialMapper = Mockito.mock(UserCredentialMapper.class);
        userBizService = Mockito.mock(UserBizService.class);
        gaotuService = Mockito.mock(GaotuService.class);

        ReflectionTestUtils.setField(controller, "userCredentialMapper", userCredentialMapper);
        ReflectionTestUtils.setField(controller, "userBizService", userBizService);
        ReflectionTestUtils.setField(controller, "gaotuService", gaotuService);
    }

    @Test
    void shouldQueryGaotuUserByMemberIdAndChannel() {
        UserCredential credential = buildCredential();
        UserVO userVO = new UserVO();
        userVO.setId(123L);
        userVO.setUserLevel(UserLevel.VIP);
        LimitSettingsOb limitSettingsOb = new LimitSettingsOb();
        limitSettingsOb.setCreateSessionLimit(500);
        userVO.setLimitSettingsOb(limitSettingsOb);

        when(userCredentialMapper.selectOne(any())).thenReturn(credential);
        when(userBizService.getUserVoById(123L)).thenReturn(userVO);

        UserVO result = controller.getGaotuUser("gt-member-1", "gaotu");

        assertEquals(123L, result.getId());
        assertEquals(UserLevel.VIP, result.getUserLevel());
        assertEquals(500, result.getLimitSettingsOb().getCreateSessionLimit());
    }

    @Test
    void shouldUpdateGaotuUserLevelByMemberId() {
        when(userCredentialMapper.selectOne(any())).thenReturn(buildCredential());

        Boolean result = controller.updateGaotuUserLevel("gt-member-1", "gaotu", UserLevel.SUPER_VIP, "2026-12-31");

        assertTrue(result);
        verify(userBizService).updateUserLevel(eq(123L), eq("gaotu"), eq(UserLevel.SUPER_VIP), any(Date.class));
    }

    @Test
    void shouldFixGaotuUserLevelUsingGaotuRights() {
        UserRightsByUserIdRes rights = new UserRightsByUserIdRes();
        rights.setUserType(1);
        Date expiredDate = new Date();
        rights.setExpirationTime(expiredDate);

        when(userCredentialMapper.selectOne(any())).thenReturn(buildCredential());
        when(gaotuService.getUserRights("gt-member-1")).thenReturn(rights);

        Boolean result = controller.fixUserLevel("gt-member-1", "gaotu");

        assertTrue(result);
        verify(userBizService).updateUserLevel(123L, "gaotu", UserLevel.VIP, expiredDate);
    }

    @Test
    void shouldRejectUnknownGaotuMemberId() {
        when(userCredentialMapper.selectOne(any())).thenReturn(null);

        assertThrows(BusinessException.class, () -> controller.getGaotuUser("missing-member", "gaotu"));
    }

    private UserCredential buildCredential() {
        UserCredential credential = new UserCredential();
        credential.setUserId(123L);
        credential.setIdentifier("gt-member-1");
        credential.setLoginType(LoginType.TOKEN);
        credential.setChannel("gaotu");
        return credential;
    }
}
