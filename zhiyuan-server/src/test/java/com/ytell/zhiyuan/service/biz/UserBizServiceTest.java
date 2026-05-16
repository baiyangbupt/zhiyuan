package com.ytell.zhiyuan.service.biz;

import com.baomidou.mybatisplus.core.toolkit.support.SFunction;
import com.baomidou.mybatisplus.extension.conditions.query.LambdaQueryChainWrapper;
import cn.hutool.core.date.DateUtil;
import com.ytell.zhiyuan.mapper.UserCredentialMapper;
import com.ytell.zhiyuan.mapper.UserMapper;
import com.ytell.zhiyuan.model.dto.LimitSettingsOb;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.LoginType;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.enums.UserLevel;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class UserBizServiceTest {

    private UserBizService userBizService;
    private UserMapper userMapper;
    private UserCredentialMapper userCredentialMapper;
    private ChatSessionSharedService chatSessionSharedService;

    @BeforeEach
    void setUp() {
        userBizService = new UserBizService();
        userMapper = Mockito.mock(UserMapper.class);
        userCredentialMapper = Mockito.mock(UserCredentialMapper.class);
        chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);

        ReflectionTestUtils.setField(userBizService, "userMapper", userMapper);
        ReflectionTestUtils.setField(userBizService, "userCredentialMapper", userCredentialMapper);
        ReflectionTestUtils.setField(userBizService, "chatSessionSharedService", chatSessionSharedService);
    }

    @Test
    void shouldAllowExpiredWhitelistMobileUser() {
        User user = buildExpiredUser(1L, "15101142787");
        when(userMapper.selectById(1L)).thenReturn(user);

        CheckRightsResVo result = userBizService.checkRights(1L, OperateCheckPoint.CreateSession);

        assertTrue(result.getCanOperate());
        verify(chatSessionSharedService, never()).lambdaQuery();
        verify(userCredentialMapper, never()).selectList(any());
    }

    @Test
    void shouldAllowExpiredWhitelistCredentialUser() {
        User user = buildExpiredUser(3L, null);
        UserCredential credential = new UserCredential();
        credential.setUserId(3L);
        credential.setLoginType(LoginType.MOBILE);
        credential.setIdentifier("15600931041");

        when(userMapper.selectById(3L)).thenReturn(user);
        when(userCredentialMapper.selectList(any())).thenReturn(Collections.singletonList(credential));

        CheckRightsResVo result = userBizService.checkRights(3L, OperateCheckPoint.CreateSession);

        assertTrue(result.getCanOperate());
    }

    @Test
    void shouldRejectExpiredNonWhitelistUser() {
        User user = buildExpiredUser(2L, "13000000000");

        when(userMapper.selectById(2L)).thenReturn(user);
        when(userCredentialMapper.selectList(any())).thenReturn(Collections.emptyList());

        CheckRightsResVo result = userBizService.checkRights(2L, OperateCheckPoint.CreateSession);

        assertFalse(result.getCanOperate());
    }

    @Test
    void shouldGenerateFiveHundredCreateSessionLimitForVipCustomer() {
        String limitSettings = userBizService.generateDefaultLimitSettings(true, "gaotu", UserLevel.VIP);

        LimitSettingsOb parsed = com.alibaba.fastjson.JSONObject.parseObject(limitSettings, LimitSettingsOb.class);

        assertEquals(500, parsed.getCreateSessionLimit());
        assertEquals(10, parsed.getModifyScoreInfoLimit());
    }

    @Test
    void shouldMapGaotuVipRightsToVipWithFiveHundredSessionLimit() {
        assertEquals(UserLevel.VIP, UserLevel.convertGaotuLevel(1));
        assertEquals(500, UserLevel.VIP.getCreateSessionLimit());
    }

    @Test
    void shouldAllowVipCreateSessionBeforeFiveHundredLimit() {
        User user = buildVipUser(4L, 500);
        when(userMapper.selectById(4L)).thenReturn(user);
        mockCreatedSessionCount(499L);

        CheckRightsResVo result = userBizService.checkRights(4L, OperateCheckPoint.CreateSession);

        assertTrue(result.getCanOperate());
    }

    @Test
    void shouldRejectVipCreateSessionAtFiveHundredLimit() {
        User user = buildVipUser(5L, 500);
        when(userMapper.selectById(5L)).thenReturn(user);
        mockCreatedSessionCount(500L);

        CheckRightsResVo result = userBizService.checkRights(5L, OperateCheckPoint.CreateSession);

        assertFalse(result.getCanOperate());
        assertEquals("您已达到创建会话次数上限（500次），无法继续创建新会话", result.getReason());
    }

    private User buildExpiredUser(Long userId, String mobile) {
        User user = new User();
        user.setId(userId);
        user.setMobile(mobile);
        user.setUserLevel(UserLevel.ORIGIN);
        user.setExpiredDate(DateUtil.offsetDay(DateUtil.date(), -1));
        LimitSettingsOb limitSettingsOb = new LimitSettingsOb();
        limitSettingsOb.setCreateSessionLimit(5);
        user.setLimitSettings(com.alibaba.fastjson.JSONObject.toJSONString(limitSettingsOb));
        return user;
    }

    private User buildVipUser(Long userId, Integer createSessionLimit) {
        User user = new User();
        user.setId(userId);
        user.setMobile("13000000000");
        user.setUserLevel(UserLevel.VIP);
        user.setExpiredDate(DateUtil.offsetDay(DateUtil.date(), 30));
        LimitSettingsOb limitSettingsOb = new LimitSettingsOb();
        limitSettingsOb.setCreateSessionLimit(createSessionLimit);
        user.setLimitSettings(com.alibaba.fastjson.JSONObject.toJSONString(limitSettingsOb));
        return user;
    }

    @SuppressWarnings("unchecked")
    private void mockCreatedSessionCount(Long count) {
        LambdaQueryChainWrapper<ChatSession> query = Mockito.mock(LambdaQueryChainWrapper.class);
        when(chatSessionSharedService.lambdaQuery()).thenReturn(query);
        when(query.eq(Mockito.<SFunction<ChatSession, ?>>any(), any())).thenReturn(query);
        when(query.count()).thenReturn(count);
    }
}
