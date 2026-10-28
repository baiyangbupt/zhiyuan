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
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(
                        new com.baomidou.mybatisplus.core.MybatisConfiguration(), ""), UserCredential.class);
        controller = new UserAdminController();
        userCredentialMapper = Mockito.mock(UserCredentialMapper.class);
        when(userCredentialMapper.selectList(any())).thenReturn(java.util.Collections.emptyList());
        userBizService = Mockito.mock(UserBizService.class);
        gaotuService = Mockito.mock(GaotuService.class);

        ReflectionTestUtils.setField(controller, "userCredentialMapper", userCredentialMapper);
        ReflectionTestUtils.setField(controller, "userBizService", userBizService);
        ReflectionTestUtils.setField(controller, "gaotuService", gaotuService);
    }

    @Test
    void newlyCreatedUsernameCredentialDoesNotStorePlaintext() {
        com.ytell.zhiyuan.mapper.UserMapper users = Mockito.mock(com.ytell.zhiyuan.mapper.UserMapper.class);
        ReflectionTestUtils.setField(controller, "userMapper", users);
        com.ytell.zhiyuan.model.req.AddUserRequest request = new com.ytell.zhiyuan.model.req.AddUserRequest();
        request.setUserName("new-user");
        request.setPassword("new-secret");
        assertTrue(controller.addUser(request));
        org.mockito.ArgumentCaptor<com.ytell.zhiyuan.model.entity.biz.User> userCapture =
                org.mockito.ArgumentCaptor.forClass(com.ytell.zhiyuan.model.entity.biz.User.class);
        verify(users).insert(userCapture.capture());
        assertEquals("new-user", userCapture.getValue().getUserName());
        org.mockito.ArgumentCaptor<UserCredential> capture = org.mockito.ArgumentCaptor.forClass(UserCredential.class);
        verify(userCredentialMapper).insert(capture.capture());
        String encoded = capture.getValue().getPasswordHash();
        org.junit.jupiter.api.Assertions.assertNotEquals("new-secret", encoded);
        assertTrue(com.ytell.zhiyuan.common.util.PasswordHashing.matches("new-secret", encoded));
        org.junit.jupiter.api.Assertions.assertFalse(com.ytell.zhiyuan.common.util.PasswordHashing.matches(encoded, encoded));
    }

    @Test
    void emptyAdminPasswordDoesNotCreateEitherRow() {
        com.ytell.zhiyuan.mapper.UserMapper users = Mockito.mock(com.ytell.zhiyuan.mapper.UserMapper.class);
        ReflectionTestUtils.setField(controller, "userMapper", users);
        com.ytell.zhiyuan.model.req.AddUserRequest request = new com.ytell.zhiyuan.model.req.AddUserRequest();
        request.setUserName("new-user");
        request.setPassword("");
        assertThrows(BusinessException.class, () -> controller.addUser(request));
        Mockito.verifyNoInteractions(users, userCredentialMapper);
    }

    @Test
    void adminCannotCreateAnotherUsernameCredentialWithTheSameIdentifier() {
        com.ytell.zhiyuan.mapper.UserMapper users = Mockito.mock(com.ytell.zhiyuan.mapper.UserMapper.class);
        ReflectionTestUtils.setField(controller, "userMapper", users);
        when(userCredentialMapper.selectList(any())).thenReturn(
                java.util.Collections.singletonList(new UserCredential()));
        com.ytell.zhiyuan.model.req.AddUserRequest request = new com.ytell.zhiyuan.model.req.AddUserRequest();
        request.setUserName("existing-user");
        request.setPassword("new-password");
        assertThrows(BusinessException.class, () -> controller.addUser(request));
        Mockito.verifyNoInteractions(users);
        Mockito.verify(userCredentialMapper, Mockito.never()).insert(any(UserCredential.class));
    }

    @Test
    void missingUsernameIsCheckedWithALockingReadAndNoPasswordPredicate() {
        com.ytell.zhiyuan.mapper.UserMapper users = Mockito.mock(com.ytell.zhiyuan.mapper.UserMapper.class);
        ReflectionTestUtils.setField(controller, "userMapper", users);
        com.ytell.zhiyuan.model.req.AddUserRequest request = new com.ytell.zhiyuan.model.req.AddUserRequest();
        request.setUserName("new-user");
        request.setPassword("new-secret");
        assertTrue(controller.addUser(request));
        org.mockito.ArgumentCaptor<com.baomidou.mybatisplus.core.conditions.Wrapper<UserCredential>> capture =
                org.mockito.ArgumentCaptor.forClass(com.baomidou.mybatisplus.core.conditions.Wrapper.class);
        verify(userCredentialMapper).selectList(capture.capture());
        String condition = capture.getValue().getSqlSegment();
        assertTrue(condition.contains("FOR UPDATE"));
        assertTrue(condition.contains("identifier"));
        org.junit.jupiter.api.Assertions.assertFalse(condition.contains("password_hash"));
        verify(userCredentialMapper, Mockito.never()).selectCount(any());
    }

    @Test
    void losingConcurrentInsertReturnsAConflictForTheTransactionToRollBack() {
        com.ytell.zhiyuan.mapper.UserMapper users = Mockito.mock(com.ytell.zhiyuan.mapper.UserMapper.class);
        ReflectionTestUtils.setField(controller, "userMapper", users);
        Mockito.doThrow(new org.springframework.dao.PessimisticLockingFailureException("synthetic deadlock"))
                .when(userCredentialMapper).insert(any(UserCredential.class));
        com.ytell.zhiyuan.model.req.AddUserRequest request = new com.ytell.zhiyuan.model.req.AddUserRequest();
        request.setUserName("new-user");
        request.setPassword("new-secret");
        BusinessException failure = assertThrows(BusinessException.class, () -> controller.addUser(request));
        assertEquals(409, failure.getStatus());
    }

    @Test
    void conflictingLockReadReturnsConflictBeforeCreatingEitherRow() {
        com.ytell.zhiyuan.mapper.UserMapper users = Mockito.mock(com.ytell.zhiyuan.mapper.UserMapper.class);
        ReflectionTestUtils.setField(controller, "userMapper", users);
        when(userCredentialMapper.selectList(any())).thenThrow(
                new org.springframework.dao.PessimisticLockingFailureException("synthetic lock timeout"));
        com.ytell.zhiyuan.model.req.AddUserRequest request = new com.ytell.zhiyuan.model.req.AddUserRequest();
        request.setUserName("new-user");
        request.setPassword("new-secret");
        BusinessException failure = assertThrows(BusinessException.class, () -> controller.addUser(request));
        assertEquals(409, failure.getStatus());
        Mockito.verifyNoInteractions(users);
        Mockito.verify(userCredentialMapper, Mockito.never()).insert(any(UserCredential.class));
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
