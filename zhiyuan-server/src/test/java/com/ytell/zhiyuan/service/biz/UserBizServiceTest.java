package com.ytell.zhiyuan.service.biz;

import com.baomidou.mybatisplus.core.toolkit.support.SFunction;
import com.baomidou.mybatisplus.extension.conditions.query.LambdaQueryChainWrapper;
import cn.hutool.core.date.DateUtil;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.mapper.UserCredentialMapper;
import com.ytell.zhiyuan.mapper.UserMapper;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.LimitSettingsOb;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.LoginType;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.enums.UserLevel;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;
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
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;

    @BeforeEach
    void setUp() {
        userBizService = new UserBizService();
        userMapper = Mockito.mock(UserMapper.class);
        userCredentialMapper = Mockito.mock(UserCredentialMapper.class);
        chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);

        ReflectionTestUtils.setField(userBizService, "userMapper", userMapper);
        ReflectionTestUtils.setField(userBizService, "userCredentialMapper", userCredentialMapper);
        ReflectionTestUtils.setField(userBizService, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(userBizService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
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

    @Test
    void shouldRejectNonSuperVipVolunteerCreateSessionAtDailyLimit() {
        User user = buildVipUser(6L, 500);
        when(userMapper.selectById(6L)).thenReturn(user);
        mockTodayVolunteerSessions(2, 0L);

        CheckRightsResVo result = userBizService.checkRights(6L, OperateCheckPoint.CreateSession, buildPrepareType("VOLUNTEER"));

        assertFalse(result.getCanOperate());
        assertEquals("智能填报期间，非SUPER_VIP用户每天最多创建2个智能填报会话", result.getReason());
    }

    @Test
    void shouldAllowNonSuperVipVolunteerCreateSessionBeforeDailyLimit() {
        User user = buildVipUser(7L, 500);
        when(userMapper.selectById(7L)).thenReturn(user);
        mockTodayVolunteerSessions(1, 10L);

        CheckRightsResVo result = userBizService.checkRights(7L, OperateCheckPoint.CreateSession, buildPrepareType("VOLUNTEER"));

        assertTrue(result.getCanOperate());
    }

    @Test
    void shouldAllowSuperVipVolunteerCreateSessionWithoutDailyLimit() {
        User user = buildVipUser(8L, 500);
        user.setUserLevel(UserLevel.SUPER_VIP);
        when(userMapper.selectById(8L)).thenReturn(user);
        mockCreatedSessionCount(10L);

        CheckRightsResVo result = userBizService.checkRights(8L, OperateCheckPoint.CreateSession, buildPrepareType("VOLUNTEER"));

        assertTrue(result.getCanOperate());
        verify(chatSessionExtraDataSharedService, never()).getBySessionIdAndDataKey(any(), any());
    }

    @Test
    void shouldNotApplyVolunteerDailyLimitToPredictCreateSession() {
        User user = buildVipUser(9L, 500);
        when(userMapper.selectById(9L)).thenReturn(user);
        mockCreatedSessionCount(10L);

        CheckRightsResVo result = userBizService.checkRights(9L, OperateCheckPoint.CreateSession, buildPrepareType("PREDICT"));

        assertTrue(result.getCanOperate());
        verify(chatSessionExtraDataSharedService, never()).getBySessionIdAndDataKey(any(), any());
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

    @SuppressWarnings("unchecked")
    private void mockTodayVolunteerSessions(int volunteerCount, Long totalCount) {
        LambdaQueryChainWrapper<ChatSession> todayQuery = Mockito.mock(LambdaQueryChainWrapper.class);
        LambdaQueryChainWrapper<ChatSession> totalQuery = Mockito.mock(LambdaQueryChainWrapper.class);
        when(chatSessionSharedService.lambdaQuery()).thenReturn(todayQuery, totalQuery);
        when(todayQuery.eq(Mockito.<SFunction<ChatSession, ?>>any(), any())).thenReturn(todayQuery);
        when(todayQuery.ge(Mockito.<SFunction<ChatSession, ?>>any(), any())).thenReturn(todayQuery);
        when(todayQuery.le(Mockito.<SFunction<ChatSession, ?>>any(), any())).thenReturn(todayQuery);
        when(todayQuery.list()).thenReturn(Arrays.asList(buildSession(101L), buildSession(102L)));
        when(totalQuery.eq(Mockito.<SFunction<ChatSession, ?>>any(), any())).thenReturn(totalQuery);
        when(totalQuery.count()).thenReturn(totalCount);

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(101L, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(buildScoreExtraData(volunteerCount >= 1 ? "VOLUNTEER" : "PREDICT"));
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(102L, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(buildScoreExtraData(volunteerCount >= 2 ? "VOLUNTEER" : "PREDICT"));
    }

    private ChatSession buildSession(Long sessionId) {
        ChatSession session = new ChatSession();
        session.setId(sessionId);
        return session;
    }

    private ChatSessionExtraData buildScoreExtraData(String prepareTypeCode) {
        ChatSessionExtraData extraData = new ChatSessionExtraData();
        CreateSessionReq req = new CreateSessionReq();
        req.setPrepareType(buildPrepareType(prepareTypeCode));
        extraData.setDataValue(JSONObject.toJSONString(req));
        return extraData;
    }

    private CreateSessionReq.PrepareType buildPrepareType(String code) {
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode(code);
        return prepareType;
    }
}
