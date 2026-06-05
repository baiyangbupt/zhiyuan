package com.ytell.zhiyuan.service.biz;

import cn.hutool.core.collection.CollectionUtil;
import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.google.common.base.Joiner;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.base.BasePage;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.ApplyTypeUtil;
import com.ytell.zhiyuan.common.util.ChatSessionExtraDataConverter;
import com.ytell.zhiyuan.common.util.JsonDataCleanUtil;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil.VolunteerFileType;
import com.ytell.zhiyuan.manager.ProvinceVolunteerStrategyManager;
import com.ytell.zhiyuan.manager.ali.AliOSSService;
import com.ytell.zhiyuan.manager.rank.VolunteerRankClient;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorRequest;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import com.ytell.zhiyuan.model.dto.gaotu.req.ProgramPageReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.RecommendNumReq;
import com.ytell.zhiyuan.model.dto.inner.ChatSessionExtraDataReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.*;
import com.ytell.zhiyuan.model.req.ChatSessionPageQuery;
import com.ytell.zhiyuan.model.vo.*;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.service.volunteer.AdvantageSubjectService;
import com.ytell.zhiyuan.service.volunteer.VolunteerDataTransformService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.io.FileUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 会话管理服务
 */
@Slf4j
@Service
public class ChatSessionBizService {

    private static final List<String> removeFiledList = Lists.newArrayList("enrollAdvice", "converProcess", "enrollMajorSubtitle", "enrollMajorId");
    private static final Map<String, JsonDataCleanUtil.StringProcessor> stringProcessors = Maps.newHashMap();

    static {
        stringProcessors.put("score", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);
        stringProcessors.put("enrollRatio", JsonDataCleanUtil.PERCENTAGE_PROCESSOR);
    }

    @Autowired
    private ChatSessionSharedService chatSessionSharedService;
    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    @Autowired
    private GaotuService gaotuService;
    @Autowired
    private AliOSSService aliOSSService;
    @Autowired
    private VolunteerDataTransformService volunteerDataTransformService;
    @Autowired
    private ChatMessageBizService chatMessageBizService;
    @Autowired
    private AdvantageSubjectService advantageSubjectService;
    @Autowired
    private ProvinceVolunteerStrategyManager volunteerStrategyManager;

    @Autowired
    private VolunteerRankClient volunteerRankClient;
    @Autowired
    private VolunteerFilePathUtil volunteerFilePathUtil;
    @Autowired
    private UserBizService userBizService;

    @Autowired
    private VolunteerDataProvider volunteerDataProvider;
    @Autowired
    private PlanningStateService planningStateService;
    @Autowired
    private VolunteerFileAsyncService volunteerFileAsyncService;

    /**
     * 分页获取用户会话列表
     *
     * @param tenantId 租户ID
     * @param req      分页查询参数
     * @return 会话分页数据
     */
    public BasePage<ChatSessionVo> pageUserSession(Long tenantId, ChatSessionPageQuery req) {

        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        Long userId = userBaseData.getUserId();
        req.setUserId(userId);
        Page<ChatSession> chatSessionList = chatSessionSharedService.pageSession(tenantId, req);
        BotVo botVo = BotVo.defaultInstance();
        List<ChatSessionVo> records = chatSessionList.getRecords().stream().map(one -> {
            String summaryData = getSessionExtraSummaryData(one);
            CreateSessionReq.PrepareType prepareType = getSessionPrepareType(one);
            return ChatSessionVo.fromEntity(one, botVo, summaryData, prepareType);
        }).collect(Collectors.toList());

        return BasePage.wrapper(chatSessionList.getCurrent(), chatSessionList.getTotal(), records);
    }

    /**
     * 更新会话的学费区间（存储在用户成绩详情中）
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @param min           学费下限
     * @param max           学费上限
     * @return 是否更新成功
     */
    public Boolean updateTuitionRange(Long tenantId, Long chatSessionId, Integer min, Integer max) {

        // 参数基本校验
        if (min != null && max != null && min > max) {
            throw new BusinessException(110, "学费下限不能大于上限");
        }

        // 读取当前会话的用户成绩详情
        ChatSessionExtraData userScoreData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (userScoreData == null || Strings.isNullOrEmpty(userScoreData.getDataValue())) {
            throw new BusinessException(110, "未找到该会话的用户成绩信息，无法更新学费区间");
        }

        CreateSessionReq scoreDetail = JSONObject.parseObject(userScoreData.getDataValue(), CreateSessionReq.class);
        if (scoreDetail == null) {
            throw new BusinessException(110, "会话用户成绩信息异常，无法更新学费区间");
        }

        CreateSessionReq.TuitionRange tuitionRange = scoreDetail.getTuitionRange();
        if (tuitionRange == null) {
            tuitionRange = new CreateSessionReq.TuitionRange();
        }
        tuitionRange.setMin(min);
        tuitionRange.setMax(max);
        scoreDetail.setTuitionRange(tuitionRange);

        userScoreData.setDataValue(JSONObject.toJSONString(scoreDetail));
        chatSessionExtraDataSharedService.updateById(userScoreData);
        return true;
    }

    /**
     * 获取用户会话详情
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @return 会话详情数据
     */
    public ChatSessionVo getUserSessionDetail(Long tenantId, Long chatSessionId) {
        ChatSession chatSession = chatSessionSharedService.getById(chatSessionId);
        BotVo botVo = BotVo.defaultInstance();
        CreateSessionReq.PrepareType prepareType = getSessionPrepareType(chatSession);
        return ChatSessionVo.fromEntity(chatSession, botVo, getSessionExtraSummaryData(chatSession), prepareType);
    }

    /**
     * 创建新的会话
     *
     * @param tenantId         租户ID
     * @param createSessionReq 创建会话请求参数
     * @return 创建的会话信息
     */
    @Transactional(rollbackFor = Exception.class)
    public ChatSessionVo createChatSession(Long tenantId, CreateSessionReq createSessionReq) {
        long requestStart = System.currentTimeMillis();

        normalizeCreateSessionDefaults(createSessionReq);
        validateCreateSessionReq(createSessionReq);

        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        //校验权益
        CheckRightsResVo checkRightsResVo = userBizService.checkRights(userBaseData.getUserId(), OperateCheckPoint.CreateSession, createSessionReq.getPrepareType());
        if (!checkRightsResVo.getCanOperate()) {
            throw new BusinessException(110, checkRightsResVo.getReason());
        }

        //特殊处理一些省份-比如新疆
        this.specialDeal(createSessionReq);
        //特殊处理，如果前端没有传递subjectList，后端补一下。
        if (CollectionUtil.isEmpty(createSessionReq.getSubjectList())) {
            log.warn("前端没有传递subjectList，后端补一下");
            //查找用户基本信息里的选科补全一下
            UserVO userVO = userBizService.getUserVoById(userBaseData.getUserId());
            if (userVO != null && userVO.getIsCustomer()
                    && userVO.getUserScoreOb() != null
                    && userVO.getUserScoreOb().getSubjectList() != null) {
                createSessionReq.setSubjectList(userVO.getUserScoreOb().getSubjectList());
            }
        }
        // 1.创建保存会话
        long saveSessionStart = System.currentTimeMillis();
        ChatSession chatSession = saveSession(tenantId, userBaseData, createSessionReq);
        log.info("createChatSession step=saveSession tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - saveSessionStart);
        // 1.1写入会话状态，供agent查询
        chatSessionExtraDataSharedService.saveOrUpdateSessionStatus(chatSession.getId(), chatSession.getSessionStatus());
        // 2.查询用户所在的填报院校专业数量
        long recommendNumStart = System.currentTimeMillis();
        RecommendNumReq req = new RecommendNumReq();
        req.setBatch(createSessionReq.getBatch().getCode());
        req.setAreaId(createSessionReq.getProvince().getCode());
        req.setSubjectType(createSessionReq.getSubjectType().getCode());
        RecommendNumResponse recommendNumResponse = gaotuService.getRecommendProgramNum(req);
        log.info("createChatSession step=getRecommendProgramNum tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - recommendNumStart);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setMajorCount(recommendNumResponse.getMajorNum());
        volunteerCount.setSchoolCount(recommendNumResponse.getSchoolNum());
        createSessionReq.setVolunteerCount(volunteerCount);

        //3.补充填报类型（专业组 or 院校+专业）
        String volunteerStrategy = volunteerStrategyManager.getVolunteerStrategyByProvinceCode(createSessionReq.getProvince().getCode(), createSessionReq.getBatch().getLevel());
        createSessionReq.setVolunteerDetailModel(volunteerStrategy);
        createSessionReq.setVolunteerModel(ApplyTypeUtil.isMajorSchoolType(volunteerStrategy) ? VolunteerModel.major : VolunteerModel.majorGroup);

        // 4.保存用户成绩等信息&用户所在批次信息&用户所在省份填报数量要求
        long saveScoreInfoStart = System.currentTimeMillis();
        saveScoreInfo(chatSession.getId(), createSessionReq);
        log.info("createChatSession step=saveScoreInfo tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - saveScoreInfoStart);

        // 5.拉取并用户志愿全量数据
        long queryAllProgramDataStart = System.currentTimeMillis();
        ProgramPageReq programPageReq = this.toProgramQuery(chatSession, createSessionReq);
        JSONObject fullData = gaotuService.queryAllProgramData(programPageReq);
        log.info("createChatSession step=queryAllProgramData tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - queryAllProgramDataStart);

        // 6.清洗&加工数据
        long cleanDataStart = System.currentTimeMillis();
        Object clearData = JsonDataCleanUtil.cleanJsonDataWithStringProcessing(fullData, removeFiledList, null, stringProcessors);
        log.info("createChatSession step=cleanVolunteerData tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - cleanDataStart);

        // 7.全量数据形成文件，本机存一份，文件存储到/tmpdata/session_volunteer_{chatSessionId}.json
        long writeLocalFileStart = System.currentTimeMillis();
        String filePath = volunteerFilePathUtil.getLocalFilePath(chatSession.getId(), VolunteerFileType.ORIGINAL);
        try {
            FileUtils.writeStringToFile(new File(filePath), JSON.toJSONString(clearData), StandardCharsets.UTF_8);
        } catch (IOException e) {
            log.error("保存本地文件失败，文件路径: {}", filePath, e);
            throw new BusinessException(110, "加载志愿数据失败");
        }
        log.info("createChatSession step=writeLocalVolunteerFile tenantId={} chatSessionId={} filePath={} costMs={}",
                tenantId, chatSession.getId(), filePath, System.currentTimeMillis() - writeLocalFileStart);

        // 7-1.异步将文件存储到oss，不阻塞建会话主链路
        String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSession.getId(), VolunteerFileType.ORIGINAL);
        volunteerFileAsyncService.uploadVolunteerFileToOss(tenantId, chatSession.getId(), ossFileName, filePath);
        log.info("createChatSession step=dispatchUploadVolunteerFileToOss tenantId={} chatSessionId={} ossFileName={}",
                tenantId, chatSession.getId(), ossFileName);

        //8-2,将用户的意向专业类和非意向专业类写入extra-data
        long saveProfileStart = System.currentTimeMillis();
        UserProfileData userProfileData = saveUserInitProfile2ExtraData(chatSession.getId(), createSessionReq);
        log.info("createChatSession step=saveUserInitProfile tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - saveProfileStart);

        //8-3，给会话插入欢迎语
        if (userProfileData != null) {
            long sendWelcomeStart = System.currentTimeMillis();
            List<CreateSessionReq.PreferredMajor> preferredMajors = createSessionReq.getPreferredMajors();
            List<String> preferredMajorNames = Lists.newArrayList();
            if (preferredMajors != null) {
                preferredMajorNames = preferredMajors.stream()
                        .map(CreateSessionReq.PreferredMajor::getMajorSubName)
                        .collect(Collectors.toList());
            }
            //用户自己选的意愿生成欢迎文案
            String preferredMajorStr = Joiner.on("、").skipNulls().join(preferredMajorNames);
            List<String> preferredRegionNames = Lists.newArrayList();
            List<CreateSessionReq.PreferredRegion> preferredRegions = createSessionReq.getPreferredRegions();
            if (preferredRegions != null) {
                preferredRegionNames = preferredRegions.stream()
                        .map(one -> one.getProvinceName())
                        .collect(Collectors.toList());
            }
            String preferredRegionStr = Joiner.on("、").skipNulls().join(preferredRegionNames);
            String welcome = String.format(
                    "你好，我是孙老师，后面由我陪你一起看志愿。我的工作方式会比较直接：先看你的分数、选科和批次能打开哪些机会，再判断专业、城市、院校是否适合，最后把方案风险和调整动作落到工作台里。\n"
                            + "我现在看到你的基本情况是：%s。\n"
                            + "已记录的关注方向：%s；地域偏好：%s。\n"
                            + "你可以直接从下面的快捷入口开始，也可以在对话框里直接问我。",
                    buildWelcomeStudentBrief(createSessionReq),
                    Strings.isNullOrEmpty(preferredMajorStr) ? "还没有特别明确的专业方向" : preferredMajorStr,
                    Strings.isNullOrEmpty(preferredRegionStr) ? "还没有特别明确的地域偏好" : preferredRegionStr
            );
            sendWelcome(tenantId, chatSession.getId(), welcome);
            log.info("createChatSession step=sendWelcome tenantId={} chatSessionId={} costMs={}",
                    tenantId, chatSession.getId(), System.currentTimeMillis() - sendWelcomeStart);
        }
        //9.更新会话状态
        long updateSessionStatusStart = System.currentTimeMillis();
        ChatSession chatSessionUp = new ChatSession();
        chatSessionUp.setId(chatSession.getId());
        chatSessionUp.setStartTime(new Date());
        chatSessionUp.setSessionStatus(SessionStatus.GOING);
        chatSessionSharedService.updateById(chatSessionUp);
        //更新
        chatSessionExtraDataSharedService.saveOrUpdateSessionStatus(chatSession.getId(), chatSessionUp.getSessionStatus());
        log.info("createChatSession step=updateSessionStatus tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - updateSessionStatusStart);

        // 10.bot基本信息
        long getBotStart = System.currentTimeMillis();
        BotVo botVo = BotVo.defaultInstance();
        log.info("createChatSession step=getBot tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - getBotStart);

        // 11.组装会话数据返回
        CreateSessionReq.PrepareType prepareType = createSessionReq.getPrepareType();
        log.info("createChatSession step=finish tenantId={} chatSessionId={} totalCostMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - requestStart);
        return ChatSessionVo.fromEntity(chatSession, botVo, getSessionExtraSummaryData(chatSession), prepareType);
    }

    private void validateCreateSessionReq(CreateSessionReq createSessionReq) {
        if (createSessionReq == null) {
            throw new BusinessException(110, "创建会话参数不能为空");
        }
        if (createSessionReq.getBatch() == null || Strings.isNullOrEmpty(createSessionReq.getBatch().getCode())) {
            throw new BusinessException(110, "请选择批次后再创建会话");
        }
        if (createSessionReq.getProvince() == null || Strings.isNullOrEmpty(createSessionReq.getProvince().getCode())) {
            throw new BusinessException(110, "请选择高考省份后再创建会话");
        }
        if (createSessionReq.getSubjectType() == null || Strings.isNullOrEmpty(createSessionReq.getSubjectType().getCode())) {
            throw new BusinessException(110, "请选择选科类型后再创建会话");
        }
        if (CollectionUtil.isEmpty(createSessionReq.getSubjectScoreList())) {
            throw new BusinessException(110, "请填写各科成绩后再创建会话");
        }
        if (createSessionReq.getTotalScore() == null) {
            throw new BusinessException(110, "请填写成绩后再创建会话");
        }
    }

    public void normalizeCreateSessionDefaults(CreateSessionReq createSessionReq) {
        if (createSessionReq == null) {
            return;
        }
        if (createSessionReq.getPrepareType() == null || Strings.isNullOrEmpty(createSessionReq.getPrepareType().getCode())) {
            CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
            prepareType.setCode("VOLUNTEER");
            prepareType.setDesc("智能填报");
            createSessionReq.setPrepareType(prepareType);
        }
        if (createSessionReq.getSex() == null || Strings.isNullOrEmpty(createSessionReq.getSex().getCode())) {
            CreateSessionReq.Sex sex = new CreateSessionReq.Sex();
            sex.setCode("female");
            sex.setName("女");
            createSessionReq.setSex(sex);
        }
        if (createSessionReq.getStrategyType() == null || Strings.isNullOrEmpty(createSessionReq.getStrategyType().getCode())) {
            CreateSessionReq.StrategyType strategyType = new CreateSessionReq.StrategyType();
            strategyType.setCode("cautious");
            strategyType.setName("稳妥型");
            createSessionReq.setStrategyType(strategyType);
        }
    }


    public List<RecommendSubMajorResponse.MajorRecommendItem> recommendMajor(Long sessionId) {
        CreateSessionReq sessionReq = volunteerDataProvider.getUserScoreDetail(sessionId);
        // 8.根据优势学科推荐专业类
        //8-1,优势学科推荐默认的适合的专业
        RecommendSubMajorRequest recommendSubMajorRequest = new RecommendSubMajorRequest();
        recommendSubMajorRequest.setStudentinfo(sessionReq);
        recommendSubMajorRequest.setTopN(8);
        RecommendSubMajorResponse recommendSubMajorResponse = volunteerRankClient.getRecommendSubMajor(recommendSubMajorRequest);
        List<RecommendSubMajorResponse.MajorRecommendItem> majorRecommendItems = recommendSubMajorResponse.getReconmandlist();
        if (majorRecommendItems.size() > 8) {
            majorRecommendItems = majorRecommendItems.subList(0, 8);
        }

        return majorRecommendItems;
    }

    public List<RecommendSubMajorResponse.MajorRecommendItem> recommendMajor(CreateSessionReq createSessionReq) {

        // 8.根据优势学科推荐专业类
        //8-1,优势学科推荐默认的适合的专业
        RecommendSubMajorRequest recommendSubMajorRequest = new RecommendSubMajorRequest();
        recommendSubMajorRequest.setStudentinfo(createSessionReq);
        recommendSubMajorRequest.setTopN(8);
        RecommendSubMajorResponse recommendSubMajorResponse = volunteerRankClient.getRecommendSubMajor(recommendSubMajorRequest);
        List<RecommendSubMajorResponse.MajorRecommendItem> majorRecommendItems = recommendSubMajorResponse.getReconmandlist();
        if (majorRecommendItems.size() > 8) {
            majorRecommendItems = majorRecommendItems.subList(0, 8);
        }

        return majorRecommendItems;
    }


    private void specialDeal(CreateSessionReq createSessionReq) {
        //新疆特殊处理
        if ("650000".equals(createSessionReq.getProvince().getCode())
                && CollectionUtil.isEmpty(createSessionReq.getSubjectList())) {
            String subjectType = createSessionReq.getSubjectType().getCode();
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
            createSessionReq.setSubjectList(subjectItemList);
        }
    }

    private void sendWelcome(Long tenantId, Long sessionId, String welcome) {
        MessageVo messageVo = new MessageVo();
        messageVo.setChatSessionId(sessionId);
        messageVo.setMessageFrom("0");
        messageVo.setContentType(ContentType.TEXT);
        messageVo.setContent(welcome);
        chatMessageBizService.saveOrUpdate(tenantId, messageVo);
    }

    private String buildWelcomeStudentBrief(CreateSessionReq createSessionReq) {
        List<String> parts = Lists.newArrayList();
        if (createSessionReq.getProvince() != null && !Strings.isNullOrEmpty(createSessionReq.getProvince().getName())) {
            parts.add(createSessionReq.getProvince().getName() + "考生");
        }
        if (createSessionReq.getTotalScore() != null) {
            parts.add(createSessionReq.getTotalScore() + "分");
        }
        if (createSessionReq.getTotalScorePos() != null) {
            parts.add("位次" + createSessionReq.getTotalScorePos());
        }
        String subjectNames = buildSubjectNames(createSessionReq.getSubjectList());
        if (!Strings.isNullOrEmpty(subjectNames)) {
            parts.add("选科" + subjectNames);
        }
        if (createSessionReq.getBatch() != null && !Strings.isNullOrEmpty(createSessionReq.getBatch().getName())) {
            parts.add(createSessionReq.getBatch().getName());
        }
        if (createSessionReq.getVolunteerModel() != null) {
            parts.add(createSessionReq.getVolunteerModel().getDesc());
        }
        if (parts.isEmpty()) {
            return "基础信息已经记录，后续我会结合当前可报机会继续分析";
        }
        return Joiner.on("，").join(parts);
    }

    private String buildSubjectNames(List<CreateSessionReq.SubjectItem> subjectList) {
        if (CollectionUtil.isEmpty(subjectList)) {
            return "";
        }
        return subjectList.stream()
                .map(CreateSessionReq.SubjectItem::getName)
                .filter(name -> !Strings.isNullOrEmpty(name))
                .collect(Collectors.joining("、"));
    }

    public List<VolunteerSchoolGroup> loadSessionVolunteerFormatData(Long chatSessionId) {
        VolunteerDataDTO volunteerDataDTO = loadChatSessionVolunteerData(chatSessionId);
        return volunteerDataTransformService.transformToVolunteerSchoolGroups(volunteerDataDTO.getDetailList(), volunteerDataDTO.getType().getCode());
    }

    public List<VolunteerSchoolGroup> transformToVolunteerSchoolGroups(VolunteerDataDTO volunteerDataDTO) {
        return volunteerDataTransformService.transformToVolunteerSchoolGroups(volunteerDataDTO.getDetailList(), volunteerDataDTO.getType().getCode());
    }

    public VolunteerDataDTO loadChatSessionVolunteerData(Long chatSessionId) {
        // 1.先从本地对应目录里找
        String localFilePath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, VolunteerFileType.ORIGINAL);
        File localFile = new File(localFilePath);

        // 如果本地文件不存在，从OSS下载
        if (!localFile.exists()) {
            log.info("本地文件不存在，尝试从OSS下载，会话ID: {}, 本地路径: {}", chatSessionId, localFilePath);

            // 基于上传时的规则拼接OSS文件名
            String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSessionId, VolunteerFileType.ORIGINAL);

            // 从OSS下载文件到本地
            boolean downloadSuccess = aliOSSService.downloadFile(ossFileName, localFilePath);
            if (!downloadSuccess) {
                log.error("从OSS下载文件失败，会话ID: {}, OSS文件名: {}", chatSessionId, ossFileName);
                throw new BusinessException(110, "下载志愿数据文件失败");
            }

            log.info("从OSS下载文件成功，会话ID: {}, 本地路径: {}", chatSessionId, localFilePath);
        }

        // 3.解析本地对应文件成DTO返回
        try {
            String jsonContent = FileUtils.readFileToString(localFile, StandardCharsets.UTF_8);
            VolunteerDataDTO volunteerDataDTO = JSONObject.parseObject(jsonContent, VolunteerDataDTO.class);
            log.info("成功加载志愿数据，会话ID: {}, 数据大小: {} bytes", chatSessionId, jsonContent.length());
            return volunteerDataDTO;
        } catch (Exception e) {
            log.error("解析本地JSON文件失败，会话ID: {}, 文件路径: {}", chatSessionId, localFilePath, e);
            throw new BusinessException(110, "解析志愿数据文件失败");
        }
    }

    /**
     * 保存会话基本信息
     *
     * @param tenantId 租户ID
     * @return 保存的会话信息
     */
    private ChatSession saveSession(Long tenantId, UserBaseData userBaseData, CreateSessionReq createSessionReq) {
        ChatSession chatSession = new ChatSession();
        chatSession.setBotId(createSessionReq.getBotId());
        chatSession.setTenantId(tenantId);
        chatSession.setUserId(userBaseData.getUserId());
        chatSession.setUserName(createSessionReq.getUserName());
        chatSession.setSessionStatus(SessionStatus.WAIT);
        return chatSessionSharedService.saveSession(chatSession);
    }

    /**
     * 保存用户成绩信息
     *
     * @param chatSessionId  会话ID
     * @param scoreDetailDTO 用户分数详情
     */
    private void saveScoreInfo(Long chatSessionId, CreateSessionReq scoreDetailDTO) {
        ChatSessionExtraData extraData = new ChatSessionExtraData();
        extraData.setChatSessionId(chatSessionId);
        extraData.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        extraData.setDataType(DataType.JSON_OBJECT);
        extraData.setDataValue(JSONObject.toJSONString(scoreDetailDTO));
        chatSessionExtraDataSharedService.save(extraData);
    }


    private ProgramPageReq toProgramQuery(ChatSession chatSession, CreateSessionReq createSessionReq) {
        ProgramPageReq req = new ProgramPageReq();
        req.setMemberId(Long.valueOf(chatSession.getUserId()));
        req.setBatch(createSessionReq.getBatch().getCode());
        req.setAreaId(createSessionReq.getProvince().getCode());
        req.setScore(createSessionReq.getTotalScore());
        req.setYear(String.valueOf(createSessionReq.getExamYear()));

        List<String> subjectFobiddenList = Lists.newArrayList("08", "10", "11");
        List<String> subjectCodeList = createSessionReq.getSubjectScoreList().stream().filter(one -> !subjectFobiddenList.contains(one.getSubject())).map(one -> one.getSubject()).sorted().collect(Collectors.toList());

        String subjects = Joiner.on("").join(subjectCodeList);
        req.setSubjects(subjects);
        req.setSubjectType(createSessionReq.getSubjectType().getCode());

        String prepareType = createSessionReq.getPrepareType() != null ? createSessionReq.getPrepareType().getCode() : "PREDICT";
        req.setPrepareType(prepareType);
        req.setSortEnum("1");
        req.setTabType(1);

        return req;
    }

    private String getSessionExtraSummaryData(ChatSession one) {
        try {
            ChatSessionExtraData userScore = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(one.getId(), ChatSessionExtraDataConstants.USER_SCORE_KEY);
            CreateSessionReq memberScoreDetailDTO = JSONObject.parseObject(userScore.getDataValue(), CreateSessionReq.class);
            // "分数/批次/省份/选科/位次"
            String batch = memberScoreDetailDTO.getBatch().getName();
            String province = memberScoreDetailDTO.getProvince().getName();
            List<String> subjectFobiddenList = Lists.newArrayList("08", "10", "11");
            List<String> subjects = memberScoreDetailDTO.getSubjectList().stream().filter(subject -> !subjectFobiddenList.contains(subject.getValue())).map(subject -> subject.getName()).collect(Collectors.toList());
            String subjectStr = Joiner.on(".").join(subjects);
            Integer score = memberScoreDetailDTO.getTotalScore();
            String customerName = Strings.isNullOrEmpty(one.getUserName()) ? "" : one.getUserName();
            //
            List<String> elementList = Lists.newArrayList();
            if (score != null) {
                elementList.add(score + "分");
            }
            if (!Strings.isNullOrEmpty(customerName)) {
                elementList.add(customerName);
            }
            if (!Strings.isNullOrEmpty(batch)) {
                elementList.add(batch);
            }
            if (!Strings.isNullOrEmpty(province)) {
                elementList.add(province);
            }
            if (!Strings.isNullOrEmpty(subjectStr)) {
                elementList.add(subjectStr);
            }
            return Joiner.on("/").skipNulls().join(elementList);
        } catch (Exception e) {
            return "";
        }
    }

    /**
     * 获取会话的prepareType
     *
     * @param chatSession 会话实体
     * @return prepareType，如果不存在则返回null
     */
    private CreateSessionReq.PrepareType getSessionPrepareType(ChatSession chatSession) {
        try {
            ChatSessionExtraData userScore = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSession.getId(), ChatSessionExtraDataConstants.USER_SCORE_KEY);
            if (userScore == null || Strings.isNullOrEmpty(userScore.getDataValue())) {
                return null;
            }
            CreateSessionReq createSessionReq = JSONObject.parseObject(userScore.getDataValue(), CreateSessionReq.class);
            return createSessionReq != null ? createSessionReq.getPrepareType() : null;
        } catch (Exception e) {
            log.warn("获取会话prepareType失败: chatSessionId={}", chatSession.getId(), e);
            return null;
        }
    }

    public ChatSessionExtraDataVo getSessionExtraDataLastVersion(Long tenantId, Long sessionId, String key) {
        ChatSessionExtraData data = chatSessionExtraDataSharedService.getBySessionIdAndDataKeyLastVersion(sessionId, key);
        ChatSessionExtraDataVo vo = new ChatSessionExtraDataVo();
        if (data == null) {
            vo.setDataVersion(-1);
            return vo;
        }
        vo.setDataVersion(data.getDataVersion());
        vo.setChatSessionId(data.getChatSessionId());
        vo.setDataKey(data.getDataKey());
        vo.setDataType(data.getDataType());
        vo.setDataValue(ChatSessionExtraDataConverter.convertToObj(data));
        return vo;
    }

    public List<ChatSessionExtraDataVo> listSessionExtraDataByKeyAndVersions(Long tenantId, Long chatSessionId, String key, List<Integer> versions) {
        List<ChatSessionExtraData> extraDataList = chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersionList(chatSessionId, key, versions);
        return extraDataList.stream().map(one -> {
            ChatSessionExtraDataVo vo = new ChatSessionExtraDataVo();
            vo.setDataVersion(one.getDataVersion());
            vo.setChatSessionId(one.getChatSessionId());
            vo.setDataKey(one.getDataKey());
            vo.setDataType(one.getDataType());

            vo.setDataValue(ChatSessionExtraDataConverter.convertToObj(one));
            return vo;
        }).collect(Collectors.toList());
    }

    public ChatSessionExtraData addOrUpdateSessionExtraData(Long tenantId, ChatSessionExtraDataReq req) {

        ChatSessionExtraData dbData = chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(req.getChatSessionId(), req.getDataKey(), req.getVersion());
        String convertedValue = ChatSessionExtraDataConverter.convertValue(req.getDataType(), req.getDataValue());
        if (dbData == null) {
            ChatSessionExtraData data = new ChatSessionExtraData();
            data.setChatSessionId(req.getChatSessionId());
            data.setDataKey(req.getDataKey());
            data.setDataType(req.getDataType());
            data.setDataVersion(req.getVersion());
            data.setDataValue(convertedValue);
            chatSessionExtraDataSharedService.save(data);
            syncPlanningProfileStateIfNeeded(req, convertedValue);
            return data;
        } else {
            dbData.setDataType(req.getDataType());
            dbData.setDataValue(convertedValue);
            chatSessionExtraDataSharedService.updateById(dbData);
            syncPlanningProfileStateIfNeeded(req, convertedValue);
            return dbData;

        }
    }

    private void syncPlanningProfileStateIfNeeded(ChatSessionExtraDataReq req, String convertedValue) {
        if (req == null
                || req.getChatSessionId() == null
                || !ChatSessionExtraDataConstants.USER_PROFILE_KEY.equals(req.getDataKey())
                || Strings.isNullOrEmpty(convertedValue)) {
            return;
        }
        try {
            UserProfileData userProfileData = JSONObject.parseObject(convertedValue, UserProfileData.class);
            planningStateService.syncProfileStateFromLegacy(
                    req.getChatSessionId(),
                    volunteerDataProvider.getUserScoreDetail(req.getChatSessionId()),
                    userProfileData,
                    true);
        } catch (Exception e) {
            log.error("sync planning profile from extra-data failed, chatSessionId={}, dataKey={}",
                    req.getChatSessionId(), req.getDataKey(), e);
        }
    }

    public Map<String, Object> getSessionExtraDataByKeyListWithVersion(Long tenantId, Long chatSessionId, List<String> keys, Integer version) {

        List<ChatSessionExtraData> extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKeyList(chatSessionId, keys, version);
        return ChatSessionExtraDataConverter.convertToMap(extraData);
    }


    /**
     * 根据学科得分比，计算出前两个优势学科
     *
     * @param createSessionReq 创建会话请求，包含学科分数信息
     * @return 前两个优势学科名称列表
     */
    public List<String> getTopTwoSubjectList(CreateSessionReq createSessionReq) {

        // 使用优势学科计算服务，根据分数比率计算优势学科
        return advantageSubjectService.getTopTwoSubjectList(createSessionReq);
    }

    /**
     * 保存专业补充数据到会话额外数据中
     *
     * @param chatSessionId 会话ID
     */
    private UserProfileData saveUserInitProfile2ExtraData(Long chatSessionId,
                                                          CreateSessionReq createSessionReq) {
        //本科还是专科
        String batchLevel = createSessionReq.getBatch().getLevel();

        // 转换为用户画像格式
        UserProfileData userProfileData = new UserProfileData();

        //1.专业信息
        //1-1 专业-正向
        List<String> level2MajorsId = Lists.newArrayList();
        List<String> level2MajorsName = Lists.newArrayList();

        //1-1-1 用户主动填写的意愿-专业类
        List<CreateSessionReq.PreferredMajor> preferredMajors = createSessionReq.getPreferredMajors();
        if (preferredMajors != null) {
            preferredMajors.forEach(one -> {
                level2MajorsId.add(one.getMajorSubId());
                level2MajorsName.add(one.getMajorSubName());
            });
        }

        //1-1-3 专业信息-正向
        UserProfileData.MajorIntent majorIntent = new UserProfileData.MajorIntent();
        majorIntent.setLevel2(level2MajorsName);
        majorIntent.setLevel2_code(level2MajorsId);
        majorIntent.setLevel2_emotion(buildDefaultEmotionList(level2MajorsName.size()));

        //1-2 专业-负向
        List<String> level2NegativeMajorsId = Lists.newArrayList();
        List<String> level2NegativeMajorsName = Lists.newArrayList();

        //1-2-1 用户主动填写的意愿-专业类
        List<CreateSessionReq.UnacceptableMajor> unacceptableMajors = createSessionReq.getUnacceptableMajors();
        if (unacceptableMajors != null) {
            unacceptableMajors.forEach(one -> {
                String majorId = one.getMajorId();
                String majorName = one.getMajorName();
                level2NegativeMajorsId.add(majorId);
                level2NegativeMajorsName.add(majorName);
            });
        }

        //1-2-2 专业信息-正向
        UserProfileData.MajorIntent majorNegativeIntent = new UserProfileData.MajorIntent();
        majorNegativeIntent.setLevel2(level2NegativeMajorsName);
        majorNegativeIntent.setLevel2_code(level2NegativeMajorsId);
        majorNegativeIntent.setLevel2_emotion(buildDefaultEmotionList(level2NegativeMajorsName.size()));

        userProfileData.setMajor_intent(majorIntent);
        userProfileData.setNegative_major_intent(majorNegativeIntent);

        // 2.学校信息（新结构）
        UserProfileData.CollegeInfo collegeInfo = new UserProfileData.CollegeInfo();
        collegeInfo.setValues(Lists.newArrayList());
        collegeInfo.setValues_code(Lists.newArrayList());
        collegeInfo.setValues_emotion(Lists.newArrayList());
        userProfileData.setCollege_info(collegeInfo);

        UserProfileData.CollegeInfo negativeCollegeInfo = new UserProfileData.CollegeInfo();
        negativeCollegeInfo.setValues(Lists.newArrayList());
        negativeCollegeInfo.setValues_code(Lists.newArrayList());
        negativeCollegeInfo.setValues_emotion(Lists.newArrayList());
        userProfileData.setNegative_college_info(negativeCollegeInfo);

        // 2.1 标签信息（新结构）
        UserProfileData.TagInfo tagInfo = new UserProfileData.TagInfo();
        tagInfo.setValues(Lists.newArrayList());
        tagInfo.setValues_emotion(Lists.newArrayList());
        userProfileData.setTag_info(tagInfo);

        UserProfileData.TagInfo negativeTagInfo = new UserProfileData.TagInfo();
        negativeTagInfo.setValues(Lists.newArrayList());
        negativeTagInfo.setValues_emotion(Lists.newArrayList());
        userProfileData.setNegative_tag_info(negativeTagInfo);

        // 2.2 优势学科信息
        UserProfileData.StrengthSubjectInfo strengthSubjectInfo = new UserProfileData.StrengthSubjectInfo();
        List<String> strengthSubjectCodes = Lists.newArrayList();
        List<String> strengthSubjectNames = Lists.newArrayList();
        List<CreateSessionReq.SubjectScore> strengthSubjectList = createSessionReq.getStrengthSubjectList();
        if (strengthSubjectList != null) {
            strengthSubjectList.forEach(one -> {
                if (one.getSubject() != null) {
                    strengthSubjectCodes.add(one.getSubject());
                }
                if (one.getSubjectName() != null) {
                    strengthSubjectNames.add(one.getSubjectName());
                }
            });
        }
        strengthSubjectInfo.setValues(strengthSubjectNames);
        strengthSubjectInfo.setValues_code(strengthSubjectCodes);
        strengthSubjectInfo.setValues_emotion(buildDefaultEmotionList(strengthSubjectNames.size()));
        userProfileData.setStrength_subject_info(strengthSubjectInfo);

        // 3.地域信息-正向
        UserProfileData.CityInfo cityInfo = new UserProfileData.CityInfo();
        //用户主动填写的意愿-省份
        List<CreateSessionReq.PreferredRegion> preferredRegions = createSessionReq.getPreferredRegions();
        List<String> provinceIds = Lists.newArrayList();
        List<String> provinceNames = Lists.newArrayList();
        if (preferredRegions != null) {
            preferredRegions.forEach(one -> {
                provinceIds.add(one.getProvinceId());
                provinceNames.add(one.getProvinceName());
            });
        }

        cityInfo.setProvince(provinceNames);
        cityInfo.setProvince_code(provinceIds);
        cityInfo.setProvince_emotion(buildDefaultEmotionList(provinceNames.size()));
        cityInfo.setCity(Lists.newArrayList());
        cityInfo.setCity_code(Lists.newArrayList());
        cityInfo.setCity_emotion(Lists.newArrayList());
        userProfileData.setCity_info(cityInfo);

        //存储初始化画像
        ChatSessionExtraData extraDataInit = new ChatSessionExtraData();
        extraDataInit.setChatSessionId(chatSessionId);
        extraDataInit.setDataKey(ChatSessionExtraDataConstants.USER_INIT_PROFILE_KEY);
        extraDataInit.setDataType(DataType.JSON_OBJECT);
        extraDataInit.setDataValue(JSONObject.toJSONString(userProfileData));
        chatSessionExtraDataSharedService.save(extraDataInit);
        log.info("用户画像数据保存成功，会话ID: {}, 推荐专业数量: {}", chatSessionId);

        //存储到对话中画像里当初始化。
        ChatSessionExtraData extraData = new ChatSessionExtraData();
        extraData.setChatSessionId(chatSessionId);
        extraData.setDataKey(ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        extraData.setDataType(DataType.JSON_OBJECT);
        extraData.setDataValue(JSONObject.toJSONString(userProfileData));
        chatSessionExtraDataSharedService.save(extraData);

        planningStateService.initializeProfileState(chatSessionId, createSessionReq, userProfileData);

        return userProfileData;
    }

    private List<String> buildDefaultEmotionList(int size) {
        List<String> result = Lists.newArrayList();
        int count = Math.max(size, 0);
        for (int i = 0; i < count; i++) {
            result.add(UserIntentEmotionLevel.defaultValue());
        }
        return result;
    }

}
