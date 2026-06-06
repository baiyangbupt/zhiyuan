package com.ytell.zhiyuan.service.biz;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.date.DateUtil;
import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Sets;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.DataDealUtil;
import com.ytell.zhiyuan.mapper.UserAuthMapper;
import com.ytell.zhiyuan.mapper.UserCredentialMapper;
import com.ytell.zhiyuan.mapper.UserMapper;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.LimitSettingsOb;
import com.ytell.zhiyuan.model.dto.ThirdChannelLoginDto;
import com.ytell.zhiyuan.model.dto.UserScoreBase;
import com.ytell.zhiyuan.model.dto.gaotu.res.UserInfoByTokenRes;
import com.ytell.zhiyuan.model.dto.gaotu.res.UserRightsByUserIdRes;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.model.entity.biz.UserAuth;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.model.enums.LoginType;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.enums.UserLevel;
import com.ytell.zhiyuan.model.req.UserInfoAddReq;
import com.ytell.zhiyuan.model.req.UserLoginRequest;
import com.ytell.zhiyuan.model.req.UserTokenLoginRequest;
import com.ytell.zhiyuan.model.vo.*;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.SmsService;
import com.ytell.zhiyuan.service.ThirdChannelLoginService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

@Service
@Slf4j
public class UserBizService {
    private static final int TEMP_CREATE_SESSION_LIMIT_FLOOR = 100;
    private static final int VOLUNTEER_DAILY_CREATE_SESSION_LIMIT = 2;
    private static final Long DEFAULT_TENANT_ID = 1L;
    private static final Long DEFAULT_BOT_ID = 1L;
    private static final String DEFAULT_CHANNEL = "ytell";
    private static final Set<String> RIGHTS_MOBILE_WHITELIST = Sets.newHashSet(
            "15101142787",
            "15600931041"
    );

    @Autowired
    private UserMapper userMapper;
    @Autowired
    private UserAuthMapper userAuthMapper;
    @Autowired
    private UserCredentialMapper userCredentialMapper;
    @Autowired
    private SmsService smsService;
    @Autowired
    private ThirdChannelLoginService thirdChannelLoginService;
    @Autowired
    private GaotuService gaotuService;
    @Autowired
    private ChatSessionSharedService chatSessionSharedService;
    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;

    public UserLoginResponse login(UserLoginRequest request) {
        QueryWrapper<UserCredential> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(UserCredential::getIdentifier, request.getUserName());
        queryWrapper.lambda().eq(UserCredential::getLoginType, LoginType.USERNAME);
        queryWrapper.lambda().eq(UserCredential::getPasswordHash, request.getPassword());
        UserCredential userCredential = userCredentialMapper.selectOne(queryWrapper);
        if (userCredential == null) {
            throw new BusinessException(404, "用户名或者密码错误");
        }
        User user = userMapper.selectById(userCredential.getUserId());
        return buildLoginResponse(user, userCredential.getLoginToken(), null);
    }

    @Transactional
    public UserLoginResponse loginByToken(UserTokenLoginRequest request) {
        UserLoginResponse response;
        //todo 不同渠道不同逻辑
        //调用高途接口获取用户信息
        UserInfoByTokenRes userInfoByTokenRes = gaotuService.getUserInfoByToken(request.getToken());
        String memberId = userInfoByTokenRes.getMemberId();
        String source = userInfoByTokenRes.getSource();
        //判断是否B端用户
        if (source != null && source.equals("B")) {
            return this.login4BByToken(request, memberId);
        }
        //C端用户流程
        //调用高途权益接口获取用户是否具备相关权益。
        UserRightsByUserIdRes userRightsByUserIdRes = gaotuService.getUserRights(memberId);
        Integer userType = userRightsByUserIdRes.getUserType();
        Date expiredDate = userRightsByUserIdRes.getExpirationTime();
        UserLevel userLevel = UserLevel.convertGaotuLevel(userType);

        //判断用户情况
        QueryWrapper<UserCredential> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(UserCredential::getIdentifier, memberId);
        queryWrapper.lambda().eq(UserCredential::getLoginType, LoginType.TOKEN);
        queryWrapper.lambda().eq(UserCredential::getChannel, request.getChannel());
        UserCredential userCredential = userCredentialMapper.selectOne(queryWrapper);

        if (userCredential != null) {
            //用户存在，更新用户等级&到期时间
            this.updateUserLevel(userCredential.getUserId(), request.getChannel(), userLevel, expiredDate);
            //更新用户头像、昵称、成绩等信息
            UserInfoAddReq addReq = buildUserInfoAddReq(userInfoByTokenRes);
            this.update(userCredential.getUserId(), addReq);
        } else {
            // 用户不存在，创建新用户
            User user = buildDefaultUser(Boolean.TRUE, request.getChannel());
            userMapper.insert(user);
            //更新用户等级&到期时间
            this.updateUserLevel(user.getId(), request.getChannel(), userLevel, expiredDate);

            //更新用户头像、昵称、成绩等信息
            UserInfoAddReq addReq = buildUserInfoAddReq(userInfoByTokenRes);
            this.update(user.getId(), addReq);

            //创建登录凭证
            userCredential = new UserCredential();
            userCredential.setIdentifier(memberId);
            userCredential.setPasswordHash(memberId);
            userCredential.setLoginToken(UUID.randomUUID().toString());
            userCredential.setLoginType(LoginType.TOKEN);
            userCredential.setChannel(request.getChannel());
            userCredential.setUserId(user.getId());
            userCredentialMapper.insert(userCredential);
        }
        //校验账户过期时间
        User user = this.getUserInfo(userCredential.getUserId());
        //组装返回
        response = buildLoginResponse(user, userCredential.getLoginToken(), request.getChannel());
        response.setHasAddInfo(true);
        return response;
    }

    @Transactional
    public UserLoginResponse login4BByToken(UserTokenLoginRequest request,  String memberId) {
        if(!request.getChannel().contains("4b")){
            request.setChannel(request.getChannel()+"4b");
        }
        //判断用户情况
        QueryWrapper<UserCredential> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(UserCredential::getIdentifier, memberId);
        queryWrapper.lambda().eq(UserCredential::getLoginType, LoginType.TOKEN);
        queryWrapper.lambda().eq(UserCredential::getChannel, request.getChannel());
        UserCredential userCredential = userCredentialMapper.selectOne(queryWrapper);

        if (userCredential == null) {
            // 用户不存在，创建新用户
            User user = buildDefaultUser(Boolean.FALSE, request.getChannel());
            userMapper.insert(user);
            //更新用户等级&到期时间
            this.updateUserLevel(user.getId(), request.getChannel(),  UserLevel.SUPER_VIP, null);

            //创建登录凭证
            userCredential = new UserCredential();
            userCredential.setIdentifier(memberId);
            userCredential.setPasswordHash(memberId);
            userCredential.setLoginToken(UUID.randomUUID().toString());
            userCredential.setLoginType(LoginType.TOKEN);
            userCredential.setChannel(request.getChannel());
            userCredential.setUserId(user.getId());
            userCredentialMapper.insert(userCredential);
        }
        //
        User user = this.getUserInfo(userCredential.getUserId());
        //组装返回
        UserLoginResponse  response = buildLoginResponse(user, userCredential.getLoginToken(), request.getChannel());
        response.setHasAddInfo(true);
        return response;
    }

    @Transactional
    public UserLoginResponse loginOrRegisterByMobile(String mobile, String code) {
        // 验证短信验证码
        smsService.verifyCode(mobile, code);

        // 查找用户是否已注册
        UserCredential userCredential = userCredentialMapper.selectOne(new QueryWrapper<UserCredential>().lambda().
                eq(UserCredential::getIdentifier, mobile).eq(UserCredential::getLoginType, LoginType.MOBILE));

        if (userCredential != null) {
            // 用户已存在，直接返回
            User user = userMapper.selectById(userCredential.getUserId());
            return buildLoginResponse(user, userCredential.getLoginToken(), null);
        }

        // 用户不存在，创建新用户
        User user = buildDefaultUser(Boolean.TRUE, DEFAULT_CHANNEL);
        user.setMobile(mobile);
        userMapper.insert(user);
        //创建登录凭证
        userCredential = new UserCredential();
        userCredential.setUserId(user.getId());
        userCredential.setLoginToken(UUID.randomUUID().toString());
        userCredential.setIdentifier(mobile);
        userCredential.setLoginType(LoginType.MOBILE);
        userCredential.setChannel(DEFAULT_CHANNEL);
        userCredentialMapper.insert(userCredential);
        //
        return buildLoginResponse(user, userCredential.getLoginToken(), null);
    }

    @Transactional
    public UserAuthVO loginOrRegisterByAuth(AuthTypeEnum authType, String appId, String code) {

        // 根据授权类型和code获取用户信息
        ThirdChannelLoginDto loginDto = thirdChannelLoginService.login(authType, appId, code);
        // 查找是否已存在授权记录
        UserAuth userAuthDb = userAuthMapper.selectOne(new QueryWrapper<UserAuth>().lambda()
                .eq(UserAuth::getAuthType, authType)
                .eq(UserAuth::getOpenId, loginDto.getOpenId()));

        User user = null;

        // 如果存在授权记录，直接返回用户登录信息
        if (userAuthDb != null) {
            return userAuthDb.toVo();
        }
        // 如果没有找到已存在的用户，创建新用户
        if (user == null) {
            user = buildDefaultUser(Boolean.TRUE, DEFAULT_CHANNEL);
            userMapper.insert(user);
        }

        // 创建新的授权记录
        UserAuth userAuth = new UserAuth();
        userAuth.setUserId(user.getId());
        userAuth.setAuthType(authType);
        userAuth.setOpenId(loginDto.getOpenId());
        userAuth.setUnionId(loginDto.getUnionId());
        userAuth.setLoginToken(UUID.randomUUID().toString());
        userAuthMapper.insert(userAuth);
        return userAuth.toVo();
    }

    public UserVO updatePhone(AuthTypeEnum authType, Long userId, String appId, String code) throws Exception {
        String phoneNumber = thirdChannelLoginService.getPhoneNumber(authType, appId, code);
        if (phoneNumber != null) {
            User base = new User();
            base.setId(userId);
            base.setMobile(phoneNumber);
            userMapper.updateById(base);
        }
        return this.getUserVoById(userId);
    }

    public UserVO getUserVoById(Long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            return null;
        }
        return convertToUserVO(user);
    }

    public User getUserInfo(Long userId) {
        return userMapper.selectById(userId);
    }

    private UserVO convertToUserVO(User user) {
        UserVO userVO = new UserVO();
        BeanUtils.copyProperties(user, userVO);
        if (!Strings.isNullOrEmpty(userVO.getMobile())) {
            userVO.setMobile(DataDealUtil.hideMiddleFourDigits(userVO.getMobile()));
        }
        if (!Strings.isNullOrEmpty(user.getUserScore())) {
            userVO.setUserScoreOb(JSONObject.parseObject(user.getUserScore(), UserScoreBase.class));
            userVO.setHasAddInfo(true);
        }
        if (!Strings.isNullOrEmpty(user.getLimitSettings())) {
            userVO.setLimitSettingsOb(JSONObject.parseObject(user.getLimitSettings(), LimitSettingsOb.class));
        }
        if (Strings.isNullOrEmpty(userVO.getUserName())) {
            userVO.setUserName("用户" + user.getId());
        }
        if (Strings.isNullOrEmpty(userVO.getAvatarUrl())) {
            userVO.setAvatarUrl("https://yuzhi-gaotu.oss-cn-beijing.aliyuncs.com/ui/default-avator.png");
        }
        return userVO;
    }


    public UserAuth getUserAuthByToken(AuthTypeEnum authType, String token) {
        UserAuth userAuth = userAuthMapper.selectOne(new QueryWrapper<UserAuth>().lambda()
                .eq(UserAuth::getLoginToken, token).eq(UserAuth::getAuthType, authType));
        if (userAuth == null) {
            return null;
        }
        return userAuth;

    }

    public UserCredential getUserCredentialByToken(String token) {
        UserCredential userAuth = userCredentialMapper.selectOne(new QueryWrapper<UserCredential>().lambda()
                .eq(UserCredential::getLoginToken, token));
        if (userAuth == null) {
            return null;
        }
        return userAuth;

    }


    public void updateUserLevel(Long userId, String channel, UserLevel userLevel, Date expiredDate) {

        User userInfo = getUserInfo(userId);
        if (userInfo == null) {
            return;
        }
        if (expiredDate == null) {
            expiredDate = DateUtil.offsetDay(new Date(), userLevel.getExpiredDays());
        }
        String limitSettings = generateDefaultLimitSettings(Boolean.TRUE, channel, userLevel);
        if (shouldUpdateUserLevel(userInfo, userLevel, expiredDate, limitSettings)) {
            User userBase = new User();
            userBase.setId(userId);
            userBase.setUserLevel(userLevel);
            userBase.setExpiredDate(expiredDate);
            userBase.setLimitSettings(limitSettings);
            userMapper.updateById(userBase);
        }
    }

    public void update(Long userId, UserInfoAddReq userInfoReq) {
        try {
            log.info("update:{}", userInfoReq);
            User userInfo = getUserInfo(userId);
            if (userInfo == null) {
                return;
            }
            User userBase = new User();
            BeanUtils.copyProperties(userInfoReq, userBase);
            if (userInfoReq.getUserScoreOb() != null) {
                UserScoreBase userScoreBase = userInfoReq.getUserScoreOb();
                //新疆特殊处理
                if ("650000".equals(userScoreBase.getProvince().getCode())
                        && CollectionUtil.isEmpty(userScoreBase.getSubjectList())) {
                    String subjectType = userScoreBase.getSubjectType().getCode();
                    List<CreateSessionReq.SubjectItem> subjectItemList = Lists.newArrayList();
                    if ("L".equals(subjectType)) {
                        subjectItemList.add(new CreateSessionReq.SubjectItem(0, "", "01", "物理"));
                        subjectItemList.add(new CreateSessionReq.SubjectItem(0, "", "05", "化学"));
                        subjectItemList.add(new CreateSessionReq.SubjectItem(0, "", "06", "生物"));
                    } else {
                        subjectItemList.add(new CreateSessionReq.SubjectItem(0, "", "02", "历史"));
                        subjectItemList.add(new CreateSessionReq.SubjectItem(0, "", "03", "政治"));
                        subjectItemList.add(new CreateSessionReq.SubjectItem(0, "", "04", "地理"));
                    }
                    userScoreBase.setSubjectList(subjectItemList);
                }

                userBase.setUserScore(JSONObject.toJSONString(userInfoReq.getUserScoreOb()));
            }
            userBase.setId(userId);
            userMapper.updateById(userBase);
        } catch (Exception e) {
            log.error("update:error:", e);
        }
    }

    /**
     * 根据用户类型和渠道生成默认的限制设置
     *
     * @param isCustomer 是否为C端用户
     * @param channel    用户渠道
     * @param userLevel  用户等级
     * @return 限制设置对象的JSON字符串
     */
    public String generateDefaultLimitSettings(Boolean isCustomer, String channel, UserLevel userLevel) {
        LimitSettingsOb limitSettings = new LimitSettingsOb();

        if (Boolean.TRUE.equals(isCustomer)) {
            // C端用户
            limitSettings.setModifyScoreInfoLimit(userLevel.getModifyScoreLimit());
            limitSettings.setCreateSessionLimit(userLevel.getCreateSessionLimit());

        } else {
            // B端用户
            limitSettings.setCreateSessionLimit(100);
            limitSettings.setModifyScoreInfoLimit(50);
        }

        log.info("生成用户限制设置，isCustomer: {}, channel: {}, createSessionLimit: {}, modifyScoreInfoLimit: {}",
                isCustomer, channel, limitSettings.getCreateSessionLimit(), limitSettings.getModifyScoreInfoLimit());

        return JSONObject.toJSONString(limitSettings);
    }

    public LimitSituationRes limitSituation(Long userId) {
        UserVO userVO = this.getUserVoById(userId);
        // 查询用户已创建的会话次数
        Long createdSessionCount = chatSessionSharedService.lambdaQuery()
                .eq(ChatSession::getUserId, userId)
                .count();
        //用户的限制
        LimitSettingsOb limitSettingsOb = userVO.getLimitSettingsOb();
        //返回
        LimitSituationRes situationRes = new LimitSituationRes();
        //创建会话的统计限制
        LimitSituationRes.SettingAndUsage createSession = new LimitSituationRes.SettingAndUsage();
        createSession.setSettingCount(resolveCreateSessionLimit(limitSettingsOb == null ? null : limitSettingsOb.getCreateSessionLimit()));
        createSession.setUseCount(createdSessionCount.intValue());
        situationRes.setCreateSession(createSession);
        return situationRes;
    }

    public CheckRightsResVo checkRights(Long userId, OperateCheckPoint checkPoint) {
        return checkRights(userId, checkPoint, null);
    }

    public CheckRightsResVo checkRights(Long userId,
                                        OperateCheckPoint checkPoint,
                                        CreateSessionReq.PrepareType prepareType) {
        CheckRightsResVo vo = new CheckRightsResVo();
        User user = this.getUserInfo(userId);
        if (user == null) {
            vo.setCanOperate(false);
            vo.setReason("用户不存在");
            return vo;
        }
        UserVO userVo = convertToUserVO(user);
        if (isRightsWhitelistUser(userId, user)) {
            vo.setCanOperate(true);
            vo.setReason("");
            return vo;
        }
        Date expiredDate = userVo.getExpiredDate();

        if (expiredDate != null && expiredDate.before(new Date())) {
            vo.setCanOperate(false);
            vo.setReason("您的VIP权益已过期，当前功能不可使用！");
            return vo;
        }
        if (OperateCheckPoint.CreateSession.equals(checkPoint)) {
            if (isVolunteerPrepareType(prepareType) && !UserLevel.SUPER_VIP.equals(userVo.getUserLevel())) {
                int createdToday = countTodayCreatedSessions(userId, "VOLUNTEER");
                if (createdToday >= VOLUNTEER_DAILY_CREATE_SESSION_LIMIT) {
                    vo.setCanOperate(false);
                    vo.setReason(String.format("智能填报期间，非SUPER_VIP用户每天最多创建%d个智能填报会话", VOLUNTEER_DAILY_CREATE_SESSION_LIMIT));
                    return vo;
                }
            }
            // 针对用户进行次数校验控制，校验创建会话总次数
            if (userVo.getLimitSettingsOb() != null && userVo.getLimitSettingsOb().getCreateSessionLimit() != null) {
                Integer createSessionLimit = resolveCreateSessionLimit(userVo.getLimitSettingsOb().getCreateSessionLimit());
                Long createdSessionCount = chatSessionSharedService.lambdaQuery()
                        .eq(ChatSession::getUserId, userId)
                        .count();
                if (createdSessionCount >= createSessionLimit) {
                    vo.setCanOperate(false);
                    vo.setReason(String.format("您已达到创建会话次数上限（%d次），无法继续创建新会话", createSessionLimit));
                    return vo;
                }
            }
        }
        if (OperateCheckPoint.ModifyScore.equals(checkPoint)) {
           //todo

        }
        if (OperateCheckPoint.DoChat.equals(checkPoint)) {
           //todo
        }
        vo.setCanOperate(true);
        vo.setReason("");
        return vo;

    }

    private boolean isRightsWhitelistUser(Long userId, User user) {
        if (user != null && RIGHTS_MOBILE_WHITELIST.contains(user.getMobile())) {
            return true;
        }
        List<UserCredential> credentialList = userCredentialMapper.selectList(new QueryWrapper<UserCredential>().lambda()
                .eq(UserCredential::getUserId, userId)
                .eq(UserCredential::getLoginType, LoginType.MOBILE));
        if (CollectionUtil.isEmpty(credentialList)) {
            return false;
        }
        return credentialList.stream()
                .map(UserCredential::getIdentifier)
                .filter(Objects::nonNull)
                .anyMatch(RIGHTS_MOBILE_WHITELIST::contains);
    }

    private Integer resolveCreateSessionLimit(Integer configuredLimit) {
        int baseLimit = configuredLimit == null ? 10 : configuredLimit;
        return Math.max(baseLimit, TEMP_CREATE_SESSION_LIMIT_FLOOR);
    }

    private boolean isVolunteerPrepareType(CreateSessionReq.PrepareType prepareType) {
        return prepareType != null && "VOLUNTEER".equals(prepareType.getCode());
    }

    private int countTodayCreatedSessions(Long userId, String prepareTypeCode) {
        List<ChatSession> todaySessions = chatSessionSharedService.lambdaQuery()
                .eq(ChatSession::getUserId, userId)
                .ge(ChatSession::getCreateTime, DateUtil.beginOfDay(new Date()))
                .le(ChatSession::getCreateTime, DateUtil.endOfDay(new Date()))
                .list();
        if (CollectionUtil.isEmpty(todaySessions)) {
            return 0;
        }
        int count = 0;
        for (ChatSession session : todaySessions) {
            if (session == null || session.getId() == null) {
                continue;
            }
            ChatSessionExtraData scoreData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                    session.getId(), ChatSessionExtraDataConstants.USER_SCORE_KEY);
            if (scoreData == null || Strings.isNullOrEmpty(scoreData.getDataValue())) {
                continue;
            }
            try {
                CreateSessionReq scoreDetail = JSONObject.parseObject(scoreData.getDataValue(), CreateSessionReq.class);
                if (scoreDetail != null
                        && scoreDetail.getPrepareType() != null
                        && prepareTypeCode.equals(scoreDetail.getPrepareType().getCode())) {
                    count++;
                }
            } catch (Exception e) {
                log.warn("countTodayCreatedSessions parse score detail failed chatSessionId={}", session.getId(), e);
            }
        }
        return count;
    }

    private User buildDefaultUser(Boolean isCustomer, String channel) {
        User user = new User();
        user.setCreateTime(new Date());
        //todo 不写死 租户id、botid
        user.setTenantId(DEFAULT_TENANT_ID);
        user.setBotId(DEFAULT_BOT_ID);
        user.setIsCustomer(isCustomer);
        user.setChannel(channel);
        user.setUserLevel(UserLevel.ORIGIN);
        user.setExpiredDate(DateUtil.offsetDay(new Date(), UserLevel.ORIGIN.getExpiredDays()));
        user.setLimitSettings(generateDefaultLimitSettings(isCustomer, channel, UserLevel.ORIGIN));
        return user;
    }

    private UserLoginResponse buildLoginResponse(User user, String loginToken, String channel) {
        UserLoginResponse response = new UserLoginResponse();
        response.setLoginToken(loginToken);
        response.setBotId(user.getBotId());
        response.setTenantId(user.getTenantId());
        response.setIsCustomer(user.getIsCustomer());
        response.setHasAddInfo(!Strings.isNullOrEmpty(user.getUserScore()));
        if (!Strings.isNullOrEmpty(channel)) {
            response.setChannel(channel);
        }
        return response;
    }

    private UserInfoAddReq buildUserInfoAddReq(UserInfoByTokenRes userInfoByTokenRes) {
        UserInfoAddReq addReq = new UserInfoAddReq();
        addReq.setUserName(userInfoByTokenRes.getUserName());
        addReq.setAvatarUrl(userInfoByTokenRes.getAvatar());
        CreateSessionReq createSessionReq = userInfoByTokenRes.toCreateSessionReq();
        if (createSessionReq != null) {
            UserScoreBase userScoreBase = new UserScoreBase();
            userScoreBase.setProvince(createSessionReq.getProvince());
            userScoreBase.setExamYear(createSessionReq.getExamYear());
            userScoreBase.setSubjectType(createSessionReq.getSubjectType());
            userScoreBase.setSubjectList(createSessionReq.getSubjectList());
            addReq.setUserScoreOb(userScoreBase);
        }
        return addReq;
    }

    private boolean shouldUpdateUserLevel(User userInfo, UserLevel targetLevel, Date expiredDate, String limitSettings) {
        if (userInfo == null) {
            return false;
        }
        if (UserLevel.VIP.equals(targetLevel)) {
            return true;
        }
        if (!Objects.equals(targetLevel, userInfo.getUserLevel())) {
            return true;
        }
        if (expiredDate != null && userInfo.getExpiredDate() != null && !userInfo.getExpiredDate().equals(expiredDate)) {
            return true;
        }
        return !Objects.equals(limitSettings, userInfo.getLimitSettings());
    }
}
