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
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
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
import com.ytell.zhiyuan.model.dto.UpdateScoreDetailRes;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import com.ytell.zhiyuan.model.dto.gaotu.req.ProgramPageReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.RecommendNumReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.ScorePositionRangeReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import com.ytell.zhiyuan.model.dto.inner.ChatSessionExtraDataReq;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerSourceDataSnapshot;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateVersionDTO;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.dto.planning.ScoreUpdatePreviewDTO;
import com.ytell.zhiyuan.model.dto.planning.StudentPlanningSummaryDTO;
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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;

import javax.annotation.PostConstruct;

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
    /** 会话详情里"最后一条提案"那一格要读它（见 `buildLastProposal`）。 */
    @Autowired
    private PendingConfirmationBizService pendingConfirmationBizService;
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
    @Autowired
    private VolunteerSourceDataSyncService volunteerSourceDataSyncService;
    @Autowired
    private ConversationAccessService conversationAccessService;
    /** score_update 动作族的 prepare 幂等/取代语义（与用户目标提案同一条状态机）。 */
    @Autowired
    private ConversationProposalRequestService conversationProposalRequestService;
    /** 补录的编码表（科目/批次/单科类省份的科类推导）。 */
    @Autowired
    private ScoreCatalogService scoreCatalogService;

    /**
     * 演示环境的 prepareType 兜底（`demo.prepare-type-fallback`，**默认空=关**）：成绩更新/取数
     * 请求缺 prepareType 时，用该值而不是按省策略实时推导。本地演示口径：上游已切 2027 填报季、
     * 省策略推出来是 VOLUNTEER，而演示会员只有 PREDICT 取数策略（确认后 84009「当前策略已失效」），
     * 配置 PREDICT 即走通。生产不配置 = 行为与今天完全一致；只把配置项加进**本地演示的启动参数**。
     */
    @Value("${demo.prepare-type-fallback:}")
    private String prepareTypeFallback;

    /** 兜底是否生效在启动时留痕：排障时不用猜配置有没有被 Spring 绑上（空/非法值明示为 off）。 */
    @PostConstruct
    void logPrepareTypeFallback() {
        String effective = configuredFallbackPrepareType();
        log.info("demo.prepare-type-fallback effective={} (empty/off=plain province-policy derivation)",
                effective == null ? "off" : effective);
    }

    /** 生效的兜底值：空/非法一律 null（=关，走省策略推导）；只有 PREDICT/VOLUNTEER 两档进请求参数。 */
    private String configuredFallbackPrepareType() {
        if (Strings.isNullOrEmpty(prepareTypeFallback)) {
            return null;
        }
        String code = prepareTypeFallback.trim().toUpperCase(Locale.ROOT);
        if (!"PREDICT".equals(code) && !"VOLUNTEER".equals(code)) {
            log.warn("demo.prepare-type-fallback ignored: unsupported value={}", prepareTypeFallback);
            return null;
        }
        return code;
    }

    private CreateSessionReq.PrepareType prepareTypeOf(String code) {
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode(code);
        prepareType.setDesc("PREDICT".equals(code) ? "模拟填报" : "智能填报");
        return prepareType;
    }

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
     * **空会话（draft）同会话补录成绩**：把"建会话时故意没做"的那几件事，
     * 在同一个会话里补齐，不再引导用户去表单新建。
     *
     * <p>顺序是有讲究的（每一步的失败都会回滚整个事务）：</p>
     * <ol>
     *   <li><b>归属</b>：租户 + 用户 + 会话三者一致，不一致与"不存在"同回 403
     *       （{@link ConversationAccessService#requireOwnedSession}）；</li>
     *   <li><b>合并</b>：空会话的 userScoreDetail 行本来就不存在，补录只带增量字段；
     *       以既有行为底做深度合并，原有 prepareType/意向等字段必须保留；</li>
     *   <li><b>校验</b>：复用建会话的 {@code normalizeCreateSessionDefaults} +
     *       {@code validateCreateSessionReq}（省份/批次/选科/各科成绩/总分）；
     *       权益走同一条 {@code checkRights}；</li>
     *   <li><b>写 userScoreDetail</b>：行不存在则 insert（空会话没有这一行），存在则 update；
     *       同时补齐 recommend 链路依赖的 volunteerCount/volunteerModel（建会话第 2-3 步）；</li>
     *   <li><b>画像</b>：仅当带意向/优势学科时，按"不覆盖既有非空值"合并写 userprofile/userInitProfile；</li>
     *   <li><b>志愿数据文件</b>：{@code fetchLatestSourceData(persist=true)} —— **必须在成绩落库之后**，
     *       它内部也读 userScoreDetail，缺行会 404；</li>
     *   <li><b>规划状态</b>：版本 +1、候选池相关置 stale、候选池成绩上下文换新
     *       （{@link PlanningStateService#applyScoreDetailUpdate}）。</li>
     * </ol>
     */
    @Transactional(rollbackFor = Exception.class)
    public UpdateScoreDetailRes updateScoreDetail(Long tenantId, Long chatSessionId, CreateSessionReq req) {
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        if (userBaseData == null || userBaseData.getUserId() == null) {
            // 没有登录身份就不做写：与"不是你的会话"同一个回包。
            throw new ConversationAccessException(403, "session_forbidden");
        }
        return doUpdateScoreDetail(tenantId, chatSessionId, req, userBaseData.getUserId());
    }

    /**
     * 补录成绩的**无登录态**入口：`userId` 由调用方从**会话行**解析（见
     * {@link ConversationAccessService#requireSessionUserId}），给待确认命令的执行路径用
     * （`/**​/inner/**` 不走登录拦截器，线程里没有 `UserBaseData`）。
     *
     * <p>两条入口共用同一条核心：合并 → 归一 → 校验（110）→ 权益 → 落库 → 志愿数据 →
     * 规划状态版本 +1 置 stale。执行路径与 REST 补录**行为必须完全一致**，
     * 否则"确认生效的"与"表单补录的"会在不同分支上分叉。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public UpdateScoreDetailRes updateScoreDetailForUser(Long tenantId, Long chatSessionId,
                                                         CreateSessionReq req, Long userId) {
        if (userId == null) {
            throw new ConversationAccessException(403, "session_forbidden");
        }
        return doUpdateScoreDetail(tenantId, chatSessionId, req, userId);
    }

    private UpdateScoreDetailRes doUpdateScoreDetail(Long tenantId, Long chatSessionId,
                                                     CreateSessionReq req, Long userId) {
        long requestStart = System.currentTimeMillis();
        if (req == null) {
            throw new BusinessException(110, "补录成绩参数不能为空");
        }
        // 1. 归属：不一致与"不存在"同回 403，不泄露会话是否存在。
        conversationAccessService.requireOwnedSession(tenantId, chatSessionId, userId);

        // 2. 以既有成绩为底合并增量（保留原有 prepareType/意愿等字段）。
        CreateSessionReq merged = mergeScoreDetail(loadSessionScoreDetail(chatSessionId), req);
        normalizeScoreUpdateDefaults(merged);
        // 2-1. 位次缺失时按一分一段补最保守位次（lowestRank）——与省缺省同一带，只补空位。
        fillTotalScorePosIfMissing(merged);

        // 3. 与建会话完全同一套校验与权益判据。
        normalizeCreateSessionDefaults(merged);
        validateCreateSessionReq(merged);
        validateScoreUpdateSubjectCodes(merged);
        CheckRightsResVo checkRightsResVo = userBizService.checkRights(
                userId, OperateCheckPoint.CreateSession, merged.getPrepareType());
        if (!Boolean.TRUE.equals(checkRightsResVo.getCanOperate())) {
            throw new BusinessException(110, checkRightsResVo.getReason());
        }
        specialDeal(merged);
        fillSubjectListFromUserProfileIfNeeded(userId, merged);

        // 4. 补齐 recommend 流水线依赖的填报数量/模式（建会话第 2-3 步）。
        long enrichStart = System.currentTimeMillis();
        enrichVolunteerCountAndModel(merged);
        log.info("updateScoreDetail step=enrichVolunteerCountModel tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSessionId, System.currentTimeMillis() - enrichStart);

        // 5. 写 userScoreDetail（空会话没有这一行 → insert）。
        upsertScoreInfo(chatSessionId, merged);

        // 6. 携带意向/优势学科时同步画像（merge 不覆盖既有非空值）。
        boolean preferenceChanged = hasProfileIntent(merged);
        UserProfileData profileData = preferenceChanged ? syncUserProfileForScoreUpdate(chatSessionId, merged) : null;

        // 7. 志愿全量数据：本机落一份 + 异步传 OSS（成绩已在上一步写好，缺行 404 不会发生）。
        long sourceDataStart = System.currentTimeMillis();
        VolunteerSourceDataSnapshot snapshot = volunteerSourceDataSyncService.fetchLatestSourceData(tenantId, chatSessionId, true);
        log.info("updateScoreDetail step=fetchLatestSourceData tenantId={} chatSessionId={} costMs={}",
                tenantId, chatSessionId, System.currentTimeMillis() - sourceDataStart);

        // 8. 规划状态：bump 版本 + 置 stale + 刷新候选池成绩上下文。
        PlanningStateVersionDTO versionDTO = planningStateService.applyScoreDetailUpdate(
                chatSessionId, merged, profileData, preferenceChanged);

        UpdateScoreDetailRes res = new UpdateScoreDetailRes();
        res.setSuccess(true);
        res.setChatSessionId(chatSessionId);
        res.setPlanningVersion(versionDTO == null ? null : versionDTO.getVersion());
        res.setStaleFlags(versionDTO == null ? null : versionDTO.getStaleFlags());
        res.setRequiresWorkspaceReload(Boolean.TRUE);
        res.setVolunteerSourceDataSynced(Boolean.TRUE);
        res.setVolunteerSourceDataFetchedAt(snapshot == null ? null : snapshot.getFetchedAt());
        log.info("updateScoreDetail step=finish tenantId={} chatSessionId={} preferenceChanged={} planningVersion={} totalCostMs={}",
                tenantId, chatSessionId, preferenceChanged, res.getPlanningVersion(), System.currentTimeMillis() - requestStart);
        return res;
    }

    // ── 补录成绩的"提案-确认"动作族（score_update）──────────────────────────────
    // 模型在对话里只表达"要补什么"（结构化草稿），Java 侧先做一次**只读校验 + 摘要**
    // （以下 preview），把预览物化成 pending（prepare），用户确认后由
    // `PendingPlanningCommandBizService` 的 `update_score_detail` 命令执行——
    // 执行体就是上面那条 `doUpdateScoreDetail`，与表单补录同一条核心。

    /**
     * 补录前的校验与结构化摘要（preview 与 prepare 共用）。
     *
     * <p>校验顺序与 {@link #doUpdateScoreDetail} 的 2-3 步一致（合并 → 归一 → **补位次** →
     * 校验 → 权益），失败抛与执行时**同一个** 110/403——预览阶段就把"确认了也注定失败"的草案挡掉，
     * 而不是等用户点了确认才回一句"未生效"。**字段集同样对齐执行集**（2026-10-07 审查 M3）：
     * 位次缺失时这里也走 {@link #fillTotalScorePosIfMissing} 向上游要一分一段（只补空位），
     * 否则卡片上少一个 {@code totalScorePos}、确认落库后又有了——预览与执行说的不是同一件事。</p>
     *
     * <p><b>边界（勿再说"不写任何东西"）</b>：预览不落 userScoreDetail、不拉志愿数据、不 bump
     * 规划版本、不置 stale——这是它相对执行段真正省掉的部分。但它并非零写：读取当前版本走
     * {@code PlanningStateService#getPlanningState}，legacy 会话的**首次读**会只补缺地懒导入
     * 规划状态行（CAS 落盘），读路径补写（edit-cache 提示 / 数据新鲜度回填）也可能落盘——都幂等、
     * 都不动版本号；补位次还会发一次上游只读查询。原 javadoc 的"只读 / 不写任何东西"名不副实
     * （2026-10-07 审查 M3），这里如实更正。</p>
     */
    public ScoreUpdatePreviewDTO previewScoreUpdate(Long tenantId, Long chatSessionId, CreateSessionReq req) {
        Long userId = conversationAccessService.requireSessionUserId(tenantId, chatSessionId);
        return buildScoreUpdatePreview(tenantId, chatSessionId, req, userId);
    }

    private ScoreUpdatePreviewDTO buildScoreUpdatePreview(Long tenantId, Long chatSessionId,
                                                          CreateSessionReq req, Long userId) {
        if (req == null || isEmptyScoreUpdateRequest(req)) {
            throw new BusinessException(110, "补录成绩参数不能为空");
        }
        conversationAccessService.requireOwnedSession(tenantId, chatSessionId, userId);
        CreateSessionReq merged = mergeScoreDetail(loadSessionScoreDetail(chatSessionId), req);
        normalizeScoreUpdateDefaults(merged);
        // 2-1. 与执行段同一步、同一个位置：位次缺失时按一分一段补最保守位次，让预览的字段集
        // 等于执行集（2026-10-07 审查 M3）。纯内存补齐 + 一次上游只读查询，不落盘。
        fillTotalScorePosIfMissing(merged);
        normalizeCreateSessionDefaults(merged);
        validateCreateSessionReq(merged);
        validateScoreUpdateSubjectCodes(merged);
        CheckRightsResVo checkRightsResVo = userBizService.checkRights(
                userId, OperateCheckPoint.CreateSession, merged.getPrepareType());
        if (!Boolean.TRUE.equals(checkRightsResVo.getCanOperate())) {
            throw new BusinessException(110, checkRightsResVo.getReason());
        }

        ScoreUpdatePreviewDTO preview = new ScoreUpdatePreviewDTO();
        preview.setStatus("ready");
        preview.setRequiresConfirmation(Boolean.TRUE);
        preview.setSourceVersion(currentPlanningVersion(chatSessionId));
        preview.setSummary(buildScoreUpdateSummary(merged));
        return preview;
    }

    /** "什么都没带"的草稿没有可确认的内容；带任一字段才允许进入预览。 */
    private boolean isEmptyScoreUpdateRequest(CreateSessionReq req) {
        return req.getProvince() == null
                && req.getSubjectType() == null
                && req.getBatch() == null
                && req.getTotalScore() == null
                && req.getTotalScorePos() == null
                && req.getExamYear() == null
                && CollectionUtil.isEmpty(req.getSubjectScoreList())
                && CollectionUtil.isEmpty(req.getSubjectList());
    }

    private Integer currentPlanningVersion(Long chatSessionId) {
        return planningStateService.getPlanningState(chatSessionId).getVersion();
    }

    /** 卡片上"给人看的那一份"：全部取自**合并后**的成绩，模型文本里的复述不作数。 */
    private Map<String, Object> buildScoreUpdateSummary(CreateSessionReq merged) {
        Map<String, Object> summary = new LinkedHashMap<String, Object>();
        if (merged.getProvince() != null) {
            putIfPresentSummary(summary, "provinceName", merged.getProvince().getName());
            putIfPresentSummary(summary, "provinceCode", merged.getProvince().getCode());
        }
        if (merged.getSubjectType() != null) {
            putIfPresentSummary(summary, "subjectType", merged.getSubjectType().getDesc());
            putIfPresentSummary(summary, "subjectTypeCode", merged.getSubjectType().getCode());
        }
        putIfPresentSummary(summary, "examYear", merged.getExamYear());
        if (merged.getBatch() != null) {
            putIfPresentSummary(summary, "batchName", merged.getBatch().getName());
            putIfPresentSummary(summary, "batchLevel", merged.getBatch().getLevel());
            if (merged.getBatch().getScore() != null) {
                putIfPresentSummary(summary, "batchScore", Math.round(merged.getBatch().getScore()));
            }
        }
        putIfPresentSummary(summary, "totalScore", merged.getTotalScore());
        putIfPresentSummary(summary, "totalScorePos", merged.getTotalScorePos());
        List<Map<String, Object>> subjects = Lists.newArrayList();
        if (merged.getSubjectScoreList() != null) {
            for (CreateSessionReq.SubjectScore item : merged.getSubjectScoreList()) {
                if (item == null || item.getScore() == null) {
                    continue;
                }
                Map<String, Object> row = new LinkedHashMap<String, Object>();
                putIfPresentSummary(row, "subject", item.getSubject());
                putIfPresentSummary(row, "subjectName", item.getSubjectName());
                row.put("score", item.getScore());
                subjects.add(row);
            }
        }
        summary.put("subjects", subjects);
        return summary;
    }

    private void putIfPresentSummary(Map<String, Object> target, String key, Object value) {
        if (value != null && !(value instanceof String && Strings.isNullOrEmpty((String) value))) {
            target.put(key, value);
        }
    }

    /**
     * 写闭环第一段（score_update）：把一次补录预览物化成**待确认**。
     *
     * <p>落进 pending 的 dataValue：`operationId`（Java 产出的幂等键，执行时必须原样复用）、
     * `proposalSource=score_update`、`sourceVersion`（确认时的计划版本守门值）、
     * `scoreUpdateRequest`（增量草稿原样——执行时由 Java 从服务端既有成绩再合并一次）、
     * `scoreSummary`（卡片展示用）。</p>
     *
     * <p>已有 pending 行时按 CAS 修订号**替换**（不是像用户目标提案那样把
     * `expectedRevision` 留在 0）：每会话一行，新的预览天然取代旧的一条；留在 0 会让
     * 第二次补录直接 40901 冲突（"pending revision conflict: current=1 expected=0"）。</p>
     */
    public PrepareResultDTO prepareScoreUpdateProposal(Long tenantId, Long chatSessionId, String requestId,
                                                       String requestDigest, CreateSessionReq req) {
        PendingConfirmationRes active = pendingConfirmationBizService.getCurrent(tenantId, chatSessionId);
        String activePendingStatus = active == null ? null : active.getStatus();
        Long expectedRevision = active == null || active.getRevision() == null ? 0L : active.getRevision();
        Long userId = conversationAccessService.requireSessionUserId(tenantId, chatSessionId);
        return conversationProposalRequestService.prepareOnce(
                tenantId, chatSessionId, requestId, requestDigest, activePendingStatus,
                () -> {
                    ScoreUpdatePreviewDTO preview = buildScoreUpdatePreview(tenantId, chatSessionId, req, userId);
                    String operationId = UUID.randomUUID().toString().replace("-", "");
                    Map<String, Object> dataValue = new LinkedHashMap<String, Object>();
                    dataValue.put("operationId", operationId);
                    dataValue.put("proposalSource", "score_update");
                    dataValue.put("sourceVersion", preview.getSourceVersion());
                    dataValue.put("scoreUpdateRequest", JSONObject.parseObject(JSONObject.toJSONString(req)));
                    dataValue.put("scoreSummary", preview.getSummary());
                    PendingConfirmationUpsertReq upsert = new PendingConfirmationUpsertReq();
                    upsert.setChatSessionId(chatSessionId);
                    upsert.setPendingId(UUID.randomUUID().toString());
                    upsert.setKind("score_update");
                    upsert.setActionFamily("update_score_detail");
                    upsert.setExpectedRevision(expectedRevision);
                    upsert.setDataValue(dataValue);
                    PendingConfirmationRes pending = pendingConfirmationBizService.upsert(tenantId, upsert);
                    return new ConversationProposalRequestService.PrepareOutcome(
                            pending == null ? null : pending.getPendingId(), operationId, preview);
                });
    }

    /**
     * 空会话的 userScoreDetail 行不存在；读取失败按"没有"处理——**返回 null、不抛 404**，
     * 交给补录去写。
     *
     * <p>public 是给只读预览用的（{@code MajorRecommendPreviewService}）：
     * 它们和写路径必须按**同一口径**读这份画像（同一张表、同一个 key、同一套解析），
     * 缺行时如实说"没有档案"而不是各自发明一种"没有"的表示。</p>
     */
    public CreateSessionReq loadSessionScoreDetail(Long chatSessionId) {
        if (chatSessionId == null) {
            return null;
        }
        try {
            ChatSessionExtraData userScoreData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                    chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
            if (userScoreData == null || Strings.isNullOrEmpty(userScoreData.getDataValue())) {
                return null;
            }
            return JSONObject.parseObject(userScoreData.getDataValue(), CreateSessionReq.class);
        } catch (Exception e) {
            log.warn("loadSessionScoreDetail failed, chatSessionId={}", chatSessionId, e);
            return null;
        }
    }

    /**
     * 补录请求只保证"增量正确"：以既有成绩 JSON 为底，把请求里**非空的**字段深度合并进去
     * （嵌套对象逐字段合并，数组/标量整体替换）。这样 prepareType、意愿、学费区间等
     * 没在补录表单里出现的字段不会被抹掉。
     */
    private CreateSessionReq mergeScoreDetail(CreateSessionReq existing, CreateSessionReq incoming) {
        JSONObject target = existing == null ? new JSONObject() : (JSONObject) JSON.toJSON(existing);
        JSONObject source = (JSONObject) JSON.toJSON(incoming);
        deepMergeJson(target, source);
        return JSONObject.parseObject(target.toJSONString(), CreateSessionReq.class);
    }

    private void deepMergeJson(JSONObject target, JSONObject source) {
        for (Map.Entry<String, Object> entry : source.entrySet()) {
            Object sourceValue = entry.getValue();
            // JSON.toJSON 会把 null 字段一并带出：null = 补录请求没带这个字段，不能覆盖既有值。
            if (sourceValue == null) {
                continue;
            }
            Object targetValue = target.get(entry.getKey());
            if (sourceValue instanceof JSONObject && targetValue instanceof JSONObject) {
                deepMergeJson((JSONObject) targetValue, (JSONObject) sourceValue);
            } else {
                target.put(entry.getKey(), sourceValue);
            }
        }
    }

    /** 补录表单不保证带这些推导字段：缺的按可推导/可兜底的值补上，避免下游拿到 "null" 年份。 */
    private void normalizeScoreUpdateDefaults(CreateSessionReq req) {
        if (req.getExamYear() == null) {
            int currentYear = java.time.Year.now().getValue();
            log.warn("updateScoreDetail: examYear missing, default to current year {}", currentYear);
            req.setExamYear(currentYear);
        }
        fillProvinceDefaultsIfMissing(req);
    }

    /**
     * 补录草稿缺**科类/填报类型**时按省策略补（2026-10-06 实测的两处缺法）。
     *
     * <p>①科类：空会话补录时模型没有任何渠道能拿到科类编码（科目表/批次表都不含科类），
     * 草稿缺科类 → 合并校验 110「请选择选科类型后再创建会话」，卡片永远出不来。单科类
     * 省份（浙江 N/综合）没有"选"的成分，按策略补上；多科类省份（江苏 WL/LS）仍报缺。</p>
     *
     * <p>②填报类型：缺省落到 VOLUNTEER（智能填报），但**上游策略是按省签发的**——本机
     * 实测 900005/浙江 的 PREDICT（模拟填报）取数成功、VOLUNTEER 直接 84009「当前策略
     * 已失效」（确认后 execute 在拉全量志愿数据那一跳炸掉）。前端口径本来就是策略优先
     * （`ScoreSupplement`/`customerDetailSession` 都取 `policy.prepareType.code`），
     * 这里对齐：只在草稿/既有成绩都没带时才推导，带了的不覆盖。</p>
     *
     * <p>③优先级（2026-10-09 演示兜底）：请求显式带 &gt; 会话存量已有（两者合并后已非空，
     * 一个字不动）&gt; 配置兜底 {@link #prepareTypeFallback} 有值 &gt; 省策略推导（现状）。
     * 上游切 2027 填报季、省策略推出来是 VOLUNTEER 而演示会员只有 PREDICT 取数策略时，
     * 本地把兜底配成 PREDICT 即可走通；**默认空=关**，生产还是省策略推导。</p>
     */
    private void fillProvinceDefaultsIfMissing(CreateSessionReq req) {
        if (req == null || req.getProvince() == null || Strings.isNullOrEmpty(req.getProvince().getCode())) {
            return;
        }
        boolean needSubjectType = req.getSubjectType() == null || Strings.isNullOrEmpty(req.getSubjectType().getCode());
        boolean needPrepareType = req.getPrepareType() == null || Strings.isNullOrEmpty(req.getPrepareType().getCode());
        if (!needSubjectType && !needPrepareType) {
            return;
        }
        String fallbackPrepareType = configuredFallbackPrepareType();
        if (needPrepareType && fallbackPrepareType != null) {
            req.setPrepareType(prepareTypeOf(fallbackPrepareType));
            log.info("scoreUpdate: prepareType missing, filled demo fallback prepareType={} province={}",
                    fallbackPrepareType, req.getProvince().getCode());
            needPrepareType = false;
            if (!needSubjectType) {
                // 唯一缺项已由兜底补齐：不再查省策略（少一跳只读查询）。
                return;
            }
        }
        ScoreCatalogService.ProvinceDefaults defaults = scoreCatalogService.provinceDefaultsOrNull(req.getProvince().getCode());
        if (defaults == null) {
            return;
        }
        if (needSubjectType && defaults.getSubjectType() != null) {
            req.setSubjectType(defaults.getSubjectType());
            log.info("scoreUpdate: subjectType missing, filled unique province subjectType={} province={}",
                    defaults.getSubjectType().getCode(), req.getProvince().getCode());
        }
        if (needPrepareType && defaults.getPrepareType() != null) {
            req.setPrepareType(defaults.getPrepareType());
            log.info("scoreUpdate: prepareType missing, filled province prepareType={} province={}",
                    defaults.getPrepareType().getCode(), req.getProvince().getCode());
        }
    }

    /**
     * 位次缺失时的**保守补齐**：向一分一段要分数所在区间，取**最保守位次 = lowestRank**
     * （同分不可分辨，区间 {highestRank~lowestRank} 里取最大名次）。口径与前端补录表单
     * 同源（`ScoreSupplement`/`PersonalInfoCollect` 同样取 `data.lowestRank` 填
     * `totalScorePos`），与 hl-wish `ScoreAlgorithmImpl.scoreToPos` 的 positionTotal
     * 约定一致、与上游 `getScorePositionRange` 的 lowestRank 数学一致。
     *
     * <p>只补**空位**：已有位次（用户填的、表单算的）永不覆盖——用户 &gt; 表。补齐需要
     * 分数/高考年份/省份/科类/批次 level 齐备，请求形状与前端一致
     * （areaId=省 code、subject=科类 code、dataLevel=批次 level、year、score）。</p>
     *
     * <p>前置不齐、上游没有该省/年份的一分一段（`data:null`）或上游查询异常：都**保持为空**，
     * 只记一条 warn——位次只是补充信息，不造数、不抛、不阻塞建档/补录主流程。</p>
     */
    private void fillTotalScorePosIfMissing(CreateSessionReq req) {
        if (req == null || req.getTotalScorePos() != null) {
            // 用户/表单已经给了位次：一个字都不动，也不查上游。
            return;
        }
        String missingInput = missingPositionLookupInput(req);
        if (missingInput != null) {
            log.warn("scorePosition: 位次缺失但输入不齐，保持为空 reason={} province={} subjectType={} batchLevel={} year={} totalScore={}",
                    missingInput, provinceCodeOf(req), subjectTypeCodeOf(req), batchLevelOf(req),
                    req.getExamYear(), req.getTotalScore());
            return;
        }
        ScorePositionRangeReq rangeReq = new ScorePositionRangeReq();
        rangeReq.setAreaId(req.getProvince().getCode());
        rangeReq.setSubject(req.getSubjectType().getCode());
        rangeReq.setDataLevel(req.getBatch().getLevel());
        rangeReq.setYear(String.valueOf(req.getExamYear()));
        rangeReq.setScore(String.valueOf(req.getTotalScore()));
        ScorePositionRangeRes range;
        try {
            range = gaotuService.getScorePositionRange(rangeReq);
        } catch (Exception ex) {
            log.warn("scorePosition: 上游查询异常，位次保持为空 areaId={} subject={} dataLevel={} year={} score={}",
                    rangeReq.getAreaId(), rangeReq.getSubject(), rangeReq.getDataLevel(),
                    rangeReq.getYear(), rangeReq.getScore(), ex);
            return;
        }
        if (range == null || range.getLowestRank() == null) {
            log.warn("scorePosition: 上游没有该省/年份的一分一段（data:null，不造数），位次保持为空 areaId={} subject={} dataLevel={} year={} score={}",
                    rangeReq.getAreaId(), rangeReq.getSubject(), rangeReq.getDataLevel(),
                    rangeReq.getYear(), rangeReq.getScore());
            return;
        }
        req.setTotalScorePos(range.getLowestRank());
        log.info("scorePosition: 位次缺失，按一分一段保守口径补齐 score={} 区间={}~{} 同分人数={} 采用lowestRank={} areaId={} subject={} dataLevel={} year={}",
                req.getTotalScore(), range.getHighestRank(), range.getLowestRank(), range.getStudents(),
                range.getLowestRank(), rangeReq.getAreaId(), rangeReq.getSubject(),
                rangeReq.getDataLevel(), rangeReq.getYear());
    }

    /** 位次推导的前置检查：返回第一条缺失项（写日志用），齐备返回 null。 */
    private String missingPositionLookupInput(CreateSessionReq req) {
        if (req.getTotalScore() == null) {
            return "totalScore";
        }
        if (req.getExamYear() == null) {
            return "examYear";
        }
        if (req.getProvince() == null || Strings.isNullOrEmpty(req.getProvince().getCode())) {
            return "province.code";
        }
        if (req.getSubjectType() == null || Strings.isNullOrEmpty(req.getSubjectType().getCode())) {
            return "subjectType.code";
        }
        if (req.getBatch() == null || Strings.isNullOrEmpty(req.getBatch().getLevel())) {
            return "batch.level";
        }
        return null;
    }

    private String provinceCodeOf(CreateSessionReq req) {
        return req.getProvince() == null ? null : req.getProvince().getCode();
    }

    private String subjectTypeCodeOf(CreateSessionReq req) {
        return req.getSubjectType() == null ? null : req.getSubjectType().getCode();
    }

    private String batchLevelOf(CreateSessionReq req) {
        return req.getBatch() == null ? null : req.getBatch().getLevel();
    }

    /** 写 userScoreDetail：行不存在则 insert（空会话），存在则整行 update。 */
    private void upsertScoreInfo(Long chatSessionId, CreateSessionReq scoreDetail) {
        ChatSessionExtraData userScoreData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (userScoreData == null) {
            saveScoreInfo(chatSessionId, scoreDetail);
            return;
        }
        userScoreData.setDataType(DataType.JSON_OBJECT);
        userScoreData.setDataValue(JSONObject.toJSONString(scoreDetail));
        chatSessionExtraDataSharedService.updateById(userScoreData);
    }

    /** 建会话第 2-3 步：填报数量与填报模式（recommend 流水线依赖 volunteerCount/volunteerModel）。 */
    private void enrichVolunteerCountAndModel(CreateSessionReq req) {
        RecommendNumReq numReq = new RecommendNumReq();
        numReq.setBatch(req.getBatch().getCode());
        numReq.setAreaId(req.getProvince().getCode());
        numReq.setSubjectType(req.getSubjectType().getCode());
        RecommendNumResponse recommendNumResponse = gaotuService.getRecommendProgramNum(numReq);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setMajorCount(recommendNumResponse.getMajorNum());
        volunteerCount.setSchoolCount(recommendNumResponse.getSchoolNum());
        req.setVolunteerCount(volunteerCount);

        String volunteerStrategy = volunteerStrategyManager.getVolunteerStrategyByProvinceCode(
                req.getProvince().getCode(), req.getBatch().getLevel());
        req.setVolunteerDetailModel(volunteerStrategy);
        req.setVolunteerModel(ApplyTypeUtil.isMajorSchoolType(volunteerStrategy) ? VolunteerModel.major : VolunteerModel.majorGroup);
    }

    private boolean hasProfileIntent(CreateSessionReq req) {
        return !CollectionUtil.isEmpty(req.getPreferredMajors())
                || !CollectionUtil.isEmpty(req.getUnacceptableMajors())
                || !CollectionUtil.isEmpty(req.getPreferredRegions())
                || !CollectionUtil.isEmpty(req.getStrengthSubjectList());
    }

    /**
     * 把补录自带的意向/优势学科合并进 userprofile 与 userInitProfile：
     * 与 {@code PlanningStateService.syncProfileStateFromLegacy} 的 fillIfEmpty 语义一致——
     * 既有非空值保留，空位才用新值填。
     */
    private UserProfileData syncUserProfileForScoreUpdate(Long chatSessionId, CreateSessionReq scoreDetail) {
        UserProfileData built = buildUserInitProfileData(scoreDetail);
        UserProfileData existing = volunteerDataProvider.getUserProfileData(chatSessionId);
        UserProfileData mergedProfile = existing == null ? built : mergeProfileKeepExisting(existing, built);
        upsertSessionExtraData(chatSessionId, ChatSessionExtraDataConstants.USER_INIT_PROFILE_KEY, mergedProfile);
        upsertSessionExtraData(chatSessionId, ChatSessionExtraDataConstants.USER_PROFILE_KEY, mergedProfile);
        return mergedProfile;
    }

    private UserProfileData mergeProfileKeepExisting(UserProfileData existing, UserProfileData incoming) {
        JSONObject target = (JSONObject) JSON.toJSON(existing);
        JSONObject source = (JSONObject) JSON.toJSON(incoming);
        fillEmptyJsonFields(target, source);
        return JSONObject.parseObject(target.toJSONString(), UserProfileData.class);
    }

    /** 只补空位：目标为空（null / 空数组）且来源非空时才写入。 */
    private void fillEmptyJsonFields(JSONObject target, JSONObject source) {
        for (Map.Entry<String, Object> entry : source.entrySet()) {
            Object sourceValue = entry.getValue();
            if (sourceValue == null) {
                continue;
            }
            Object targetValue = target.get(entry.getKey());
            if (sourceValue instanceof JSONObject) {
                if (targetValue instanceof JSONObject) {
                    fillEmptyJsonFields((JSONObject) targetValue, (JSONObject) sourceValue);
                } else if (targetValue == null) {
                    target.put(entry.getKey(), sourceValue);
                }
                continue;
            }
            boolean targetEmpty = targetValue == null
                    || (targetValue instanceof java.util.Collection && ((java.util.Collection<?>) targetValue).isEmpty());
            boolean sourceEmpty = sourceValue instanceof java.util.Collection && ((java.util.Collection<?>) sourceValue).isEmpty();
            if (targetEmpty && !sourceEmpty) {
                target.put(entry.getKey(), sourceValue);
            }
        }
    }

    private void upsertSessionExtraData(Long chatSessionId, String dataKey, Object value) {
        String dataValue = JSONObject.toJSONString(value);
        ChatSessionExtraData existing = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSessionId, dataKey);
        if (existing == null) {
            ChatSessionExtraData extraData = new ChatSessionExtraData();
            extraData.setChatSessionId(chatSessionId);
            extraData.setDataKey(dataKey);
            extraData.setDataType(DataType.JSON_OBJECT);
            extraData.setDataValue(dataValue);
            chatSessionExtraDataSharedService.save(extraData);
            return;
        }
        existing.setDataType(DataType.JSON_OBJECT);
        existing.setDataValue(dataValue);
        chatSessionExtraDataSharedService.updateById(existing);
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
        CreateSessionReq scoreDetail = getSessionScoreDetail(chatSession);
        CreateSessionReq.PrepareType prepareType = scoreDetail != null ? scoreDetail.getPrepareType() : null;
        ChatSessionVo vo = ChatSessionVo.fromEntity(chatSession, botVo, getSessionExtraSummaryData(chatSession), prepareType);
        vo.setExamYear(scoreDetail != null ? scoreDetail.getExamYear() : null);
        vo.setStudentSummary(buildStudentPlanningSummary(scoreDetail));
        vo.setLastProposal(buildLastProposal(tenantId, chatSessionId));
        return vo;
    }

    /**
     * 会话里**最后一条**提案的状态——给浏览器冷加载把卡片画出来（见 {@link LastProposalVo}）。
     *
     * <p>取的是**待确认的当前行**（`pendingConfirmationBizService.getCurrent`）：它就是"最近一次提案"，
     * 且带着动作落定后的状态（applied / cancelled / expired），不做额外过滤——
     * 冷加载要的恰恰是"已经落定的那一条"。
     */
    private LastProposalVo buildLastProposal(Long tenantId, Long chatSessionId) {
        PendingConfirmationRes pending;
        try {
            pending = pendingConfirmationBizService.getCurrent(tenantId, chatSessionId);
        } catch (Exception ex) {
            // 详情接口不该因为提案那一格取不到就整个失败：卡片少一张，会话照常打开。
            log.warn("getUserSessionDetail: lastProposal unavailable, chatSessionId={}", chatSessionId, ex);
            return null;
        }
        if (pending == null || Strings.isNullOrEmpty(pending.getPendingId())) {
            return null;
        }
        Object proposalId = null;
        Object sourceVersion = null;
        Map<String, Object> dataValue = pending.getDataValue();
        if (dataValue != null) {
            proposalId = dataValue.get("proposalId");
            sourceVersion = dataValue.get("sourceVersion");
        }
        return LastProposalVo.builder()
                .proposalRef(pending.getPendingId())
                .proposalId(proposalId == null ? null : String.valueOf(proposalId))
                .actionStatus(pending.getStatus())
                .sourceVersion(asInteger(sourceVersion))
                .revision(pending.getRevision())
                // 冷加载兜底卡要渲染成"像一张卡"（2026-10-08：只给 ref 时前端落兜底标题
                // "方案调整预览"、明细全丢 ✗）：补录族把 scoreSummary 带上，前端可拼出
                // "更新成绩"标题与结构化明细；其余（方案调整）保持原样。
                .kind(pending.getKind())
                .scoreSummary(dataValue == null ? null : dataValue.get("scoreSummary"))
                .build();
    }

    /** `dataValue` 里的值是 JSON 反序列化出来的 `Object`：不是数字就当作没有，别让详情接口为此报错。 */
    private Integer asInteger(Object value) {
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        if (value == null) {
            return null;
        }
        try {
            return Integer.valueOf(String.valueOf(value).trim());
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private StudentPlanningSummaryDTO buildStudentPlanningSummary(CreateSessionReq scoreDetail) {
        StudentPlanningSummaryDTO summary = new StudentPlanningSummaryDTO();
        if (scoreDetail == null) {
            return summary;
        }
        summary.setSex(formatSex(scoreDetail.getSex()));
        summary.setScore(scoreDetail.getTotalScore());
        summary.setRank(scoreDetail.getTotalScorePos());
        if (scoreDetail.getBatch() != null) {
            summary.setBatchName(defaultString(scoreDetail.getBatch().getName()));
            if (scoreDetail.getBatch().getScore() != null) {
                summary.setBatchScore(Math.round(scoreDetail.getBatch().getScore()));
            }
        }
        if (scoreDetail.getProvince() != null) {
            summary.setProvinceName(defaultString(scoreDetail.getProvince().getName()));
        }
        summary.setSubjects(resolveSubjectNames(scoreDetail.getSubjectList()));
        summary.setStrengthSubjects(resolveStrengthSubjects(scoreDetail));
        return summary;
    }

    private String formatSex(CreateSessionReq.Sex sex) {
        if (sex == null) {
            return "";
        }
        String name = defaultString(sex.getName());
        if (!Strings.isNullOrEmpty(name)) {
            return name;
        }
        String code = defaultString(sex.getCode()).toLowerCase(Locale.ROOT);
        if ("male".equals(code) || "m".equals(code) || "1".equals(code) || "男".equals(code)) {
            return "男";
        }
        if ("female".equals(code) || "f".equals(code) || "2".equals(code) || "女".equals(code)) {
            return "女";
        }
        return defaultString(sex.getCode());
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private List<String> resolveSubjectNames(List<CreateSessionReq.SubjectItem> subjectList) {
        if (subjectList == null) {
            return Lists.newArrayList();
        }
        return subjectList.stream()
                .filter(Objects::nonNull)
                .map(CreateSessionReq.SubjectItem::getName)
                .filter(name -> !Strings.isNullOrEmpty(name))
                .distinct()
                .collect(Collectors.toList());
    }

    private List<String> resolveStrengthSubjects(CreateSessionReq scoreDetail) {
        if (scoreDetail == null || scoreDetail.getStrengthSubjectList() == null) {
            return Lists.newArrayList();
        }
        return scoreDetail.getStrengthSubjectList().stream()
                .filter(Objects::nonNull)
                .map(CreateSessionReq.SubjectScore::getSubjectName)
                .filter(name -> !Strings.isNullOrEmpty(name))
                .distinct()
                .collect(Collectors.toList());
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
        if (Boolean.TRUE.equals(createSessionReq.getDraft())) {
            return createEmptyChatSession(tenantId, createSessionReq, requestStart);
        }
        validateCreateSessionReq(createSessionReq);
        // 归一之后：位次缺失时按一分一段补最保守位次（lowestRank）；已有位次/前置不齐则原样。
        fillTotalScorePosIfMissing(createSessionReq);

        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        //校验权益
        CheckRightsResVo checkRightsResVo = userBizService.checkRights(userBaseData.getUserId(), OperateCheckPoint.CreateSession, createSessionReq.getPrepareType());
        if (!checkRightsResVo.getCanOperate()) {
            throw new BusinessException(110, checkRightsResVo.getReason());
        }

        //特殊处理一些省份-比如新疆
        this.specialDeal(createSessionReq);
        //特殊处理，如果前端没有传递subjectList，后端补一下。
        fillSubjectListFromUserProfileIfNeeded(userBaseData.getUserId(), createSessionReq);
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
            String welcome = buildWelcomeMessage(createSessionReq, preferredMajorStr, preferredRegionStr);
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
        ChatSessionVo vo = ChatSessionVo.fromEntity(chatSession, botVo, getSessionExtraSummaryData(chatSession), prepareType);
        vo.setExamYear(createSessionReq.getExamYear());
        vo.setStudentSummary(buildStudentPlanningSummary(createSessionReq));
        return vo;
    }

    /**
     * 建一个**什么都不带**的会话：不在建会话时采集信息，也不拉全量志愿数据。
     *
     * <p>为什么需要这条分支：原来的"创建会话"= 采集信息 + 拉该省全量志愿数据
     * （见 {@link #createChatSession} 第 2–7 步），所以省份/批次/选科/成绩被做成了
     * 硬校验。但那几项本来就是**对话要达到目标时要采集的信息**——先拦一道表单，
     * 等于把"采集"这件事挪到对话之外，而对话恰恰是最该做这件事的地方。</p>
     *
     * <p>这里**故意**不写成绩、不拉数据、不发欢迎语：会话一旦带上占位信息，
     * 模型就会把它当成已知条件，反而不会再问缺什么。</p>
     *
     * <p>权益校验保留——空会话也是会话，判据不该因为信息空着而放宽。</p>
     */
    private ChatSessionVo createEmptyChatSession(Long tenantId, CreateSessionReq createSessionReq, long requestStart) {
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        CheckRightsResVo checkRightsResVo = userBizService.checkRights(
                userBaseData.getUserId(), OperateCheckPoint.CreateSession, createSessionReq.getPrepareType());
        if (!checkRightsResVo.getCanOperate()) {
            throw new BusinessException(110, checkRightsResVo.getReason());
        }
        if (createSessionReq.getBotId() == null) {
            throw new BusinessException(110, "botId 不能为空");
        }
        ChatSession chatSession = saveSession(tenantId, userBaseData, createSessionReq);
        chatSessionExtraDataSharedService.saveOrUpdateSessionStatus(chatSession.getId(), chatSession.getSessionStatus());

        ChatSession going = new ChatSession();
        going.setId(chatSession.getId());
        going.setStartTime(new Date());
        going.setSessionStatus(SessionStatus.GOING);
        chatSessionSharedService.updateById(going);
        chatSessionExtraDataSharedService.saveOrUpdateSessionStatus(chatSession.getId(), going.getSessionStatus());

        log.info("createEmptyChatSession tenantId={} chatSessionId={} totalCostMs={}",
                tenantId, chatSession.getId(), System.currentTimeMillis() - requestStart);

        ChatSessionVo vo = ChatSessionVo.fromEntity(
                chatSession, BotVo.defaultInstance(), getSessionExtraSummaryData(chatSession),
                createSessionReq.getPrepareType());
        vo.setExamYear(createSessionReq.getExamYear());
        vo.setStudentSummary(buildStudentPlanningSummary(createSessionReq));
        return vo;
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

    /**
     * 补录各科的**编码加固**（2026-10-06 真事故）：模型只报分数不报科目的草稿
     * （`subjectScoreList=[{"score":88},{"score":85}]`）合并后 `subject=null`，
     * 一路流到组查询串的拼接处才炸（NPE → 回包 `code:-1 message:null`，
     * 用户只看到"失败"两个字，连失败原因都没有）。
     *
     * <p>在**落库之前**以业务码 110 挡下：每个元素都必须带非空 `subject`，且是标准编码
     * （01-07 选考 + 08/10/11 语数外，口径见
     * {@link ScoreCatalogService#STANDARD_SUBJECT_CODES}）。缺 `subjectName` 的按编码补一个
     * ——卡上给人看的是名称，模型只给编码时不能让卡显示成光秃秃的"08 118"。</p>
     *
     * <p>元素为 null、编码为空、编码非标准，三者同一句话（模型能做的动作是一样的：
     * 先查编码表再补一次），不逐项挤牙膏。</p>
     */
    private void validateScoreUpdateSubjectCodes(CreateSessionReq req) {
        if (req == null || CollectionUtil.isEmpty(req.getSubjectScoreList())) {
            // 空列表由 validateCreateSessionReq 负责（110「请填写各科成绩后再创建会话」）。
            return;
        }
        for (CreateSessionReq.SubjectScore item : req.getSubjectScoreList()) {
            if (item == null || Strings.isNullOrEmpty(item.getSubject())
                    || !ScoreCatalogService.isStandardSubjectCode(item.getSubject())) {
                throw new BusinessException(110, "非标准选科编码");
            }
            String code = item.getSubject().trim();
            item.setSubject(code);
            if (Strings.isNullOrEmpty(item.getSubjectName())) {
                item.setSubjectName(ScoreCatalogService.subjectNameFor(code));
            }
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
        return callRecommendSubMajor(recommendSubMajorRequest);
    }

    public List<RecommendSubMajorResponse.MajorRecommendItem> recommendMajor(CreateSessionReq createSessionReq) {

        // 8.根据优势学科推荐专业类
        //8-1,优势学科推荐默认的适合的专业
        RecommendSubMajorRequest recommendSubMajorRequest = new RecommendSubMajorRequest();
        recommendSubMajorRequest.setStudentinfo(createSessionReq);
        recommendSubMajorRequest.setTopN(8);
        return callRecommendSubMajor(recommendSubMajorRequest);
    }

    private List<RecommendSubMajorResponse.MajorRecommendItem> callRecommendSubMajor(RecommendSubMajorRequest recommendSubMajorRequest) {
        try {
            RecommendSubMajorResponse recommendSubMajorResponse = volunteerRankClient.getRecommendSubMajor(recommendSubMajorRequest);
            if (recommendSubMajorResponse == null || CollectionUtil.isEmpty(recommendSubMajorResponse.getReconmandlist())) {
                return Collections.emptyList();
            }
            List<RecommendSubMajorResponse.MajorRecommendItem> majorRecommendItems = recommendSubMajorResponse.getReconmandlist();
            if (majorRecommendItems.size() > 8) {
                majorRecommendItems = majorRecommendItems.subList(0, 8);
            }
            return majorRecommendItems;
        } catch (RuntimeException e) {
            log.warn("专业意向默认推荐暂不可用，降级为空列表，采集流程继续: cause={}, req={}", e.toString(), recommendSubMajorRequest);
            return Collections.emptyList();
        }
    }


    /** 前端没传 subjectList 时，用用户基本信息里的选科补全（建会话与空会话补录共用）。 */
    private void fillSubjectListFromUserProfileIfNeeded(Long userId, CreateSessionReq createSessionReq) {
        if (!CollectionUtil.isEmpty(createSessionReq.getSubjectList())) {
            return;
        }
        log.warn("前端没有传递subjectList，后端补一下");
        //查找用户基本信息里的选科补全一下
        UserVO userVO = userBizService.getUserVoById(userId);
        if (userVO != null && userVO.getIsCustomer()
                && userVO.getUserScoreOb() != null
                && userVO.getUserScoreOb().getSubjectList() != null) {
            createSessionReq.setSubjectList(userVO.getUserScoreOb().getSubjectList());
        }
        // **画像之外的第二来源：单科成绩**（2026-10-08 空值兼容 ✓✓）：从零/空档案会话没有 C 端
        // 画像 ✗，而"选考三科"明明就在 `subjectScoreList` 里（编码 01-07 为选考，08/10/11 为语数外）✓
        //——用户口径："上面都给了，不该再问" ✓；优势科目同样按单科成绩推导（选考降序取前 2，
        // 同分按编码升序；只补空位，已有不动 ✓）。
        fillSubjectListFromScoresIfNeeded(createSessionReq);
    }

    /** 选考科目编码：01-07（01 物理 / 02 历史 / 03 政治 / 04 地理 / 05 化学 / 06 生物 / 07）；语数外 08/10/11。 */
    private static final java.util.Set<String> ELECTIVE_SUBJECT_CODES =
            new java.util.HashSet<String>(java.util.Arrays.asList("01", "02", "03", "04", "05", "06", "07"));

    private void fillSubjectListFromScoresIfNeeded(CreateSessionReq req) {
        List<CreateSessionReq.SubjectScore> scores = req.getSubjectScoreList();
        if (CollectionUtil.isEmpty(scores)) {
            return;
        }
        List<CreateSessionReq.SubjectScore> electives = Lists.newArrayList();
        for (CreateSessionReq.SubjectScore score : scores) {
            if (score == null || Strings.isNullOrEmpty(score.getSubject())) {
                continue;
            }
            if (ELECTIVE_SUBJECT_CODES.contains(score.getSubject())) {
                electives.add(score);
            }
        }
        if (electives.isEmpty()) {
            return;
        }
        if (CollectionUtil.isEmpty(req.getSubjectList())) {
            List<CreateSessionReq.SubjectItem> subjectItems = Lists.newArrayList();
            for (CreateSessionReq.SubjectScore score : electives) {
                subjectItems.add(new CreateSessionReq.SubjectItem(0, "",
                        score.getSubject(),
                        Strings.isNullOrEmpty(score.getSubjectName()) ? score.getSubject() : score.getSubjectName()));
            }
            req.setSubjectList(subjectItems);
            log.info("subjectList derived from subjectScoreList, size={}", subjectItems.size());
        }
        if (CollectionUtil.isEmpty(req.getStrengthSubjectList())) {
            List<CreateSessionReq.SubjectScore> ranked = Lists.newArrayList(electives);
            ranked.sort((a, b) -> {
                int sa = a.getScore() == null ? Integer.MIN_VALUE : a.getScore();
                int sb = b.getScore() == null ? Integer.MIN_VALUE : b.getScore();
                if (sa != sb) {
                    return Integer.compare(sb, sa);
                }
                return String.valueOf(a.getSubject()).compareTo(String.valueOf(b.getSubject()));
            });
            int take = Math.min(2, ranked.size());
            req.setStrengthSubjectList(Lists.newArrayList(ranked.subList(0, take)));
            log.info("strengthSubjectList derived from subjectScoreList, size={}", take);
        }
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

    private String buildWelcomeMessage(CreateSessionReq createSessionReq,
                                       String preferredMajorStr,
                                       String preferredRegionStr) {
        String welcomeTarget = buildWelcomeTargetName(createSessionReq.getUserName());
        String prepareTypeDesc = createSessionReq.getPrepareType() == null
                ? "志愿填报"
                : createSessionReq.getPrepareType().getDesc();
        String strategyDesc = createSessionReq.getStrategyType() == null
                ? "结合冲、稳、保梯度逐步校准"
                : createSessionReq.getStrategyType().getName();
        String majorPreference = Strings.isNullOrEmpty(preferredMajorStr)
                ? "暂未记录特别明确的专业方向，后续可以一起梳理兴趣、能力和职业倾向"
                : preferredMajorStr;
        String regionPreference = Strings.isNullOrEmpty(preferredRegionStr)
                ? "暂未记录特别明确的地域偏好，后续会结合城市机会和家庭预期一起判断"
                : preferredRegionStr;

        return String.format(
                "%s，我是孙老师。接下来我会陪你把这次%s按步骤看清楚：先核对分数、位次、选科和批次，再结合院校、专业、城市、学费和风险梯度，逐步把可执行的志愿方案落到右侧工作台里。\n"
                        + "我现在看到的基础信息是：%s。当前服务会重点关注候选机会筛选、冲稳保结构、方案排序、风险审查和必要的调整建议。\n"
                        + "已记录的专业关注：%s；地域偏好：%s；填报策略：%s。\n"
                        + "如果这些信息有变化，可以直接告诉我；如果先从现有方案看起，也可以使用下方快捷入口。",
                welcomeTarget,
                prepareTypeDesc,
                buildWelcomeStudentBrief(createSessionReq),
                majorPreference,
                regionPreference,
                Strings.isNullOrEmpty(strategyDesc) ? "结合冲、稳、保梯度逐步校准" : strategyDesc
        );
    }

    private String buildWelcomeTargetName(String userName) {
        if (Strings.isNullOrEmpty(userName)) {
            return "你好";
        }
        String normalizedName = userName.trim();
        if (Strings.isNullOrEmpty(normalizedName)) {
            return "你好";
        }
        return normalizedName + "同学你好";
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
        // 组查询的四个维度缺一不可：以前是在这里直接 getXxx().getCode() —— 批次/省份/科类
        // 任一为空就是 NPE（回包 code:-1 message:null，失败原因被吞掉）。缺项要回**能行动的** 110。
        if (createSessionReq.getBatch() == null || Strings.isNullOrEmpty(createSessionReq.getBatch().getCode())
                || createSessionReq.getProvince() == null || Strings.isNullOrEmpty(createSessionReq.getProvince().getCode())
                || createSessionReq.getSubjectType() == null || Strings.isNullOrEmpty(createSessionReq.getSubjectType().getCode())) {
            throw new BusinessException(110, "成绩信息不完整，请先补全省份、批次与科类");
        }
        List<String> subjectCodeList = ScoreCatalogService.electiveSubjectCodes(createSessionReq.getSubjectScoreList());
        if (subjectCodeList.isEmpty()) {
            // 全被过滤或全为空码：以前这里会拼出空串甚至炸在流的 null 上；空串上游不报错、
            // 只返回空，看起来像"没有数据"。宁可直接 110。
            throw new BusinessException(110, "成绩信息缺少选考科目编码");
        }
        ProgramPageReq req = new ProgramPageReq();
        req.setMemberId(Long.valueOf(chatSession.getUserId()));
        req.setBatch(createSessionReq.getBatch().getCode());
        req.setAreaId(createSessionReq.getProvince().getCode());
        req.setScore(createSessionReq.getTotalScore());
        req.setYear(String.valueOf(createSessionReq.getExamYear()));

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
        CreateSessionReq createSessionReq = getSessionScoreDetail(chatSession);
        return createSessionReq != null ? createSessionReq.getPrepareType() : null;
    }

    private CreateSessionReq getSessionScoreDetail(ChatSession chatSession) {
        try {
            ChatSessionExtraData userScore = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSession.getId(), ChatSessionExtraDataConstants.USER_SCORE_KEY);
            if (userScore == null || Strings.isNullOrEmpty(userScore.getDataValue())) {
                return null;
            }
            return JSONObject.parseObject(userScore.getDataValue(), CreateSessionReq.class);
        } catch (Exception e) {
            log.warn("获取会话分数信息失败: chatSessionId={}", chatSession.getId(), e);
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
        UserProfileData userProfileData = buildUserInitProfileData(createSessionReq);

        //存储初始化画像
        upsertSessionExtraData(chatSessionId, ChatSessionExtraDataConstants.USER_INIT_PROFILE_KEY, userProfileData);
        log.info("用户画像数据保存成功，会话ID: {}, 推荐专业数量: {}", chatSessionId);

        //存储到对话中画像里当初始化。
        upsertSessionExtraData(chatSessionId, ChatSessionExtraDataConstants.USER_PROFILE_KEY, userProfileData);

        planningStateService.initializeProfileState(chatSessionId, createSessionReq, userProfileData);

        return userProfileData;
    }

    /** 由 CreateSessionReq 构造初始化画像（纯构造，不落库）；建会话与空会话补录共用。 */
    private UserProfileData buildUserInitProfileData(CreateSessionReq createSessionReq) {
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
