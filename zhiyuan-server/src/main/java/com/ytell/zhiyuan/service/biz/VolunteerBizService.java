package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.ExcelUtil;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil.VolunteerFileType;
import com.ytell.zhiyuan.manager.ali.AliOSSService;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.SchoolRecommendResponse;
import com.ytell.zhiyuan.model.dto.inner.SimulateDiffRequest;
import com.ytell.zhiyuan.model.dto.inner.SimulateDiffResponse;
import com.ytell.zhiyuan.model.dto.inner.UserIntentQueryReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.io.FileUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 志愿处理上下文
 * 封装志愿推荐处理过程中的核心数据
 */
@Data
class VolunteerProcessContext {
    // 必需的核心数据 - 这些是实际被使用的
    private CreateSessionReq userScoreDetail;
    private UserProfileData userFinalProfileData;
    private String applyType;
    private Map<String, Integer> threeTargetCountMap;
    private List<VolunteerSchoolGroup> volunteerAfterFilterData;
}

/**
 * 志愿填报管理服务
 */
@Slf4j
@Service
public class VolunteerBizService {

    @Autowired
    private VolunteerDataProvider dataProvider;
    @Autowired
    private VolunteerFilterChain filterChain;
    @Autowired
    private VolunteerSorterAndMerger sorterAndMerger;
    @Autowired
    private VolunteerResponseBuilder responseBuilder;
    @Autowired
    private VolunteerUtils utils;
    @Autowired
    private VolunteerIntervalService volunteerIntervalService;
    @Autowired
    private AliOSSService aliOSSService;
    @Autowired
    private ChatSessionSharedService chatSessionSharedService;
    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    @Autowired
    private VolunteerFilePathUtil volunteerFilePathUtil;


    /**
     * 获取志愿推荐列表
     *
     * @param tenantId
     * @param chatSessionId
     * @param split
     * @param saveToFile
     * @return
     */
    public VolunteerRecommendListResponse recommendVolunteerList(Long tenantId, Long chatSessionId, boolean split, boolean saveToFile) {
        // 1. 获取会话详情
        ChatSession chatSession = dataProvider.getChatSession(chatSessionId);

        // 如果会话里方案已经提交，直接返回当时提交的结果
        if (SessionStatus.FINISHED.equals(chatSession.getSessionStatus())) {
            return this.loadFinalSubmitVolunteerData(chatSession.getId());
        }

        // 否则进行查询推荐-排序
        VolunteerRecommendListResponse response = doRecommendVolunteerList(tenantId, chatSessionId, split);
        //保存到oss
        try {
            //保存下排序结果，用于对其进行分析
            if (saveToFile) {
                // 1. 生成本地临时文件路径
                String tempFilePath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, VolunteerFileType.TEMP_RECOMMEND);

                // 2. 将结果序列化为JSON并写入本地文件
                FileUtils.writeStringToFile(new File(tempFilePath), JSON.toJSONString(response), StandardCharsets.UTF_8);
                log.info("志愿推荐结果已保存到本地文件: {}", tempFilePath);

                // 3. 上传到OSS
                String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSessionId, VolunteerFileType.TEMP_RECOMMEND);
                String etag = aliOSSService.uploadFile(ossFileName, new File(tempFilePath));
                log.info("志愿推荐结果已上传到OSS，文件名: {}, ETag: {}", ossFileName, etag);

                // 4. 生成并保存摘要文件
                savePlanSummary(chatSessionId, response, VolunteerFileType.TEMP_SUMMARY);
            }
        } catch (Exception e) {
            log.error("recommendVolunteerList:saveToFile:fail", e);
        }
        return response;
    }

    /**
     * 准备志愿数据 - 提取公共逻辑
     *
     * @param chatSessionId         会话ID
     * @return 志愿处理上下文
     */
    private VolunteerProcessContext prepareVolunteerData(Long chatSessionId) {
        VolunteerProcessContext context = new VolunteerProcessContext();

        // 1. 获取用户数据
        CreateSessionReq userScoreDetail = dataProvider.getUserScoreDetail(chatSessionId);
        UserProfileData userProfileData = dataProvider.getUserProfileData(chatSessionId);


        // 2. 合并用户画像
        UserProfileData userFinalProfileData = utils.mergeUserProfile(userProfileData);
        log.info("prepareVolunteerData:userFinalProfileData:{}", userFinalProfileData);

        // 3. 获取志愿数据
        VolunteerDataDTO volunteerDataDTO = dataProvider.getVolunteerDataDTO(chatSessionId);
        List<VolunteerSchoolGroup> volunteerFullData = dataProvider.transformToVolunteerSchoolGroups(volunteerDataDTO);
        String applyType = dataProvider.getApplyTypeCode(volunteerDataDTO);

        // 4. 计算目标数量
        Integer targetSchoolCount = dataProvider.calculateTargetSchoolCount(userScoreDetail, applyType);
        Map<String, Integer> threeTargetCountMap = volunteerIntervalService.calculateTargetCounts(targetSchoolCount, false, userScoreDetail.getStrategyType());

        // 5. 构建筛选条件
        UserIntentQueryReq userIntentQueryReq = filterChain.buildQueryCondition(userScoreDetail, userFinalProfileData);

        // 6. 过滤志愿数据
        List<VolunteerSchoolGroup> volunteerAfterFilterData = filterChain.filterVolunteerData(userIntentQueryReq, volunteerFullData);
        log.info("志愿过滤后数据: {}", volunteerAfterFilterData.size());
        // 只设置实际需要的字段
        context.setUserScoreDetail(userScoreDetail);
        context.setUserFinalProfileData(userFinalProfileData);
        context.setApplyType(applyType);
        context.setThreeTargetCountMap(threeTargetCountMap);
        context.setVolunteerAfterFilterData(volunteerAfterFilterData);
        return context;
    }

    /**
     * 执行志愿推荐列表
     */
    public VolunteerRecommendListResponse doRecommendVolunteerList(Long tenantId, Long chatSessionId, Boolean split) {
        log.info("getVolunteerRecommendList: tenantId={}, chatSessionId={}, split={}", tenantId, chatSessionId, split);

        // 获取处理后的志愿数据
        VolunteerProcessContext context = prepareVolunteerData(chatSessionId);

        // 排序和截断
        Map<String, List<VolunteerSchoolGroup>> sortedIntervalData = sorterAndMerger.sortAndSplitByInterval(context.getVolunteerAfterFilterData(), context.getUserScoreDetail(), context.getUserFinalProfileData(), context.getApplyType(), split, context.getThreeTargetCountMap());

        // 构建响应数据
        return responseBuilder.buildVolunteerRecommendResponse(sortedIntervalData, context.getUserScoreDetail(), context.getUserFinalProfileData(), context.getApplyType(), context.getThreeTargetCountMap());
    }

    /**
     * 准备志愿数据（使用指定画像覆盖数据库画像）
     * 用于模拟对比场景：不修改持久化画像，仅在内存中使用 proposedProfile 走推荐流水线。
     */
    private VolunteerProcessContext prepareVolunteerDataWithProfile(Long chatSessionId, UserProfileData proposedProfile) {
        VolunteerProcessContext context = new VolunteerProcessContext();

        // 1. 获取用户成绩（不变）
        CreateSessionReq userScoreDetail = dataProvider.getUserScoreDetail(chatSessionId);

        // 1-1. 获取
        UserProfileData userMedianProfileData = dataProvider.getUserProfileData(chatSessionId);
        log.info("prepareVolunteerDataWithProfile:userMedianProfileData:{}", userMedianProfileData);

        // 2. 使用传入的画像，走合并逻辑
        UserProfileData userFinalProfileData = utils.mergeUserProfile(proposedProfile);
        log.info("prepareVolunteerDataWithProfile:userFinalProfileData:{}", userFinalProfileData);

        // 3-6 同 prepareVolunteerData
        VolunteerDataDTO volunteerDataDTO = dataProvider.getVolunteerDataDTO(chatSessionId);
        List<VolunteerSchoolGroup> volunteerFullData = dataProvider.transformToVolunteerSchoolGroups(volunteerDataDTO);
        String applyType = dataProvider.getApplyTypeCode(volunteerDataDTO);

        Integer targetSchoolCount = dataProvider.calculateTargetSchoolCount(userScoreDetail, applyType);
        Map<String, Integer> threeTargetCountMap = volunteerIntervalService.calculateTargetCounts(targetSchoolCount, false, userScoreDetail.getStrategyType());

        UserIntentQueryReq userIntentQueryReq = filterChain.buildQueryCondition(userScoreDetail, userFinalProfileData);
        List<VolunteerSchoolGroup> volunteerAfterFilterData = filterChain.filterVolunteerData(userIntentQueryReq, volunteerFullData);
        log.info("模拟志愿过滤后数据: {}", volunteerAfterFilterData.size());

        context.setUserScoreDetail(userScoreDetail);
        context.setUserFinalProfileData(userFinalProfileData);
        context.setApplyType(applyType);
        context.setThreeTargetCountMap(threeTargetCountMap);
        context.setVolunteerAfterFilterData(volunteerAfterFilterData);
        return context;
    }

    /**
     * 模拟画像变更对志愿方案的影响。
     * 不会修改任何持久化数据，仅在内存中用 proposedProfile 重新走推荐流水线，
     * 然后与当前缓存方案做 diff。
     *
     * @param tenantId        租户ID
     * @param chatSessionId   会话ID
     * @param request         模拟对比请求（含拟修改后的完整画像）
     * @return 方案差异摘要
     */
    public SimulateDiffResponse simulateDiff(Long tenantId, Long chatSessionId, SimulateDiffRequest request) {
        log.info("simulateDiff: tenantId={}, chatSessionId={}", tenantId, chatSessionId);

        // 1. 加载当前缓存的推荐结果
        VolunteerRecommendListResponse currentPlan = loadCachedRecommendData(chatSessionId);
        if (currentPlan == null) {
            log.warn("simulateDiff: 当前无缓存方案，先执行一次推荐");
            currentPlan = doRecommendVolunteerList(tenantId, chatSessionId, false);
        }

        // 2. 用拟修改画像重新走推荐流水线
        VolunteerProcessContext context = prepareVolunteerDataWithProfile(chatSessionId, request.getProposedProfile());
        Map<String, List<VolunteerSchoolGroup>> sortedIntervalData = sorterAndMerger.sortAndSplitByInterval(
                context.getVolunteerAfterFilterData(), context.getUserScoreDetail(),
                context.getUserFinalProfileData(), context.getApplyType(),
                false, context.getThreeTargetCountMap());
        VolunteerRecommendListResponse newPlan = responseBuilder.buildVolunteerRecommendResponse(
                sortedIntervalData, context.getUserScoreDetail(),
                context.getUserFinalProfileData(), context.getApplyType(),
                context.getThreeTargetCountMap());

        // 3. 计算 diff
        return computeDiff(currentPlan, newPlan);
    }

    /**
     * 计算两个推荐方案之间的差异（基于水位线）。
     * 对比每个区间（冲/稳/保）水位线以内的学校集合变化，
     * 而非全量列表的跨区间对比。
     */
    private SimulateDiffResponse computeDiff(VolunteerRecommendListResponse oldPlan, VolunteerRecommendListResponse newPlan) {
        // 获取各区间水位线（targetCount）
        Map<String, Integer> oldTargets = oldPlan.getBaseData().getThree_target_count_map();
        Map<String, Integer> newTargets = newPlan.getBaseData().getThree_target_count_map();

        // 构建 schoolId → name 的映射
        Map<String, String> schoolNames = new HashMap<>();
        buildSchoolNameMap(oldPlan, schoolNames);
        buildSchoolNameMap(newPlan, schoolNames);

        List<SimulateDiffResponse.SchoolDiff> promoted = new ArrayList<>();
        List<SimulateDiffResponse.SchoolDiff> demoted = new ArrayList<>();

        // 对冲/稳/保分别做水位线内对比
        compareWithinWaterline(oldPlan.getSprints(), newPlan.getSprints(),
                oldTargets.getOrDefault("sprints_count", 0),
                newTargets.getOrDefault("sprints_count", 0),
                "sprint", schoolNames, promoted, demoted);

        compareWithinWaterline(oldPlan.getSafes(), newPlan.getSafes(),
                oldTargets.getOrDefault("safes_count", 0),
                newTargets.getOrDefault("safes_count", 0),
                "safe", schoolNames, promoted, demoted);

        compareWithinWaterline(oldPlan.getProtects(), newPlan.getProtects(),
                oldTargets.getOrDefault("protects_count", 0),
                newTargets.getOrDefault("protects_count", 0),
                "protect", schoolNames, promoted, demoted);

        return SimulateDiffResponse.builder()
                .before(buildTierSummary(oldPlan))
                .after(buildTierSummary(newPlan))
                .promoted(promoted)
                .demoted(demoted)
                .build();
    }

    /**
     * 对比单个区间水位线内的学校集合变化。
     */
    private void compareWithinWaterline(
            List<VolunteerRecommendListResponse.VolunteerSchool> oldList,
            List<VolunteerRecommendListResponse.VolunteerSchool> newList,
            int oldTargetCount, int newTargetCount,
            String tier, Map<String, String> schoolNames,
            List<SimulateDiffResponse.SchoolDiff> promoted,
            List<SimulateDiffResponse.SchoolDiff> demoted) {

        Set<String> oldPreferred = extractPreferredIds(oldList, oldTargetCount);
        Set<String> newPreferred = extractPreferredIds(newList, newTargetCount);

        // 新进入水位线的
        for (String id : newPreferred) {
            if (!oldPreferred.contains(id)) {
                promoted.add(SimulateDiffResponse.SchoolDiff.builder()
                        .schoolId(id)
                        .schoolName(schoolNames.getOrDefault(id, id))
                        .tier(tier)
                        .build());
            }
        }

        // 移出水位线的
        for (String id : oldPreferred) {
            if (!newPreferred.contains(id)) {
                demoted.add(SimulateDiffResponse.SchoolDiff.builder()
                        .schoolId(id)
                        .schoolName(schoolNames.getOrDefault(id, id))
                        .tier(tier)
                        .build());
            }
        }
    }

    /**
     * 从列表中取前 targetCount 个学校的 schoolId 集合（水位线以内）。
     */
    private Set<String> extractPreferredIds(
            List<VolunteerRecommendListResponse.VolunteerSchool> list, int targetCount) {
        if (list == null || list.isEmpty()) {
            return Collections.emptySet();
        }
        Set<String> ids = new HashSet<>();
        int limit = Math.min(targetCount, list.size());
        for (int i = 0; i < limit; i++) {
            ids.add(list.get(i).getSchoolId());
        }
        return ids;
    }

    private void buildSchoolNameMap(VolunteerRecommendListResponse plan, Map<String, String> names) {
        if (plan.getSprints() != null) {
            plan.getSprints().forEach(s -> names.putIfAbsent(s.getSchoolId(), s.getSchool_name()));
        }
        if (plan.getSafes() != null) {
            plan.getSafes().forEach(s -> names.putIfAbsent(s.getSchoolId(), s.getSchool_name()));
        }
        if (plan.getProtects() != null) {
            plan.getProtects().forEach(s -> names.putIfAbsent(s.getSchoolId(), s.getSchool_name()));
        }
    }

    private SimulateDiffResponse.TierSummary buildTierSummary(VolunteerRecommendListResponse plan) {
        int sprint = plan.getSprints() != null ? plan.getSprints().size() : 0;
        int safe = plan.getSafes() != null ? plan.getSafes().size() : 0;
        int protect = plan.getProtects() != null ? plan.getProtects().size() : 0;
        return SimulateDiffResponse.TierSummary.builder()
                .sprintCount(sprint)
                .safeCount(safe)
                .protectCount(protect)
                .totalCount(sprint + safe + protect)
                .build();
    }


    /**
     * 推荐学校专业方法
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @param split         是否使用截断逻辑
     * @return 推荐的学校专业列表
     */
    public SchoolRecommendResponse recommendSchoolMajors(Long tenantId, Long chatSessionId, Boolean split) {
        log.info("recommendSchoolMajors: tenantId={}, chatSessionId={}, split={}", tenantId, chatSessionId, split);

        // 获取方案列表
        VolunteerRecommendListResponse response = this.loadCachedRecommendData(chatSessionId);
        //录取概率过滤
        RecommendReq recommendReq = new RecommendReq();
        recommendReq.setMinEnrollRate(45d);
        recommendReq.setMaxEnrollRate(60d);

        // 构建学校推荐响应
        return responseBuilder.buildSchoolRecommendResponse(response,recommendReq);
    }


    public SchoolRecommendResponse recommendSchoolMajor(Long tenantId, Long chatSessionId, RecommendReq recommendReq) {
        log.info("recommendSchoolMajors: tenantId={}, chatSessionId={}, recommendReq={}", tenantId, chatSessionId, recommendReq);

        // 获取方案列表
        VolunteerRecommendListResponse response = this.loadCachedRecommendData(chatSessionId);

        // 构建学校推荐响应
        return responseBuilder.buildSchoolRecommendResponse(response,recommendReq);
    }

    /**
     * 加载缓存的推荐结果数据
     * 优先从本地读取，如果本地不存在则从OSS下载
     *
     * @param chatSessionId 会话ID
     * @return 缓存的推荐结果数据
     */
    public VolunteerRecommendListResponse loadCachedRecommendData(Long chatSessionId) {
        // 1. 先从本地对应目录里找
        String localFilePath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, VolunteerFileType.TEMP_RECOMMEND);
        File localFile = new File(localFilePath);

        // 如果本地文件不存在，从OSS下载
        if (!localFile.exists()) {
            log.info("本地缓存文件不存在，尝试从OSS下载，会话ID: {}, 本地路径: {}", chatSessionId, localFilePath);

            // 基于上传时的规则拼接OSS文件名
            String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSessionId, VolunteerFileType.TEMP_RECOMMEND);

            // 从OSS下载文件到本地
            boolean downloadSuccess = aliOSSService.downloadFile(ossFileName, localFilePath);
            if (!downloadSuccess) {
                log.error("从OSS下载缓存文件失败，会话ID: {}, OSS文件名: {}", chatSessionId, ossFileName);
                throw new BusinessException(110, "下载缓存推荐数据文件失败");
            }

            log.info("从OSS下载缓存文件成功，会话ID: {}, 本地路径: {}", chatSessionId, localFilePath);
        }

        // 3. 解析本地对应文件成DTO返回
        try {
            String jsonContent = FileUtils.readFileToString(localFile, StandardCharsets.UTF_8);
            VolunteerRecommendListResponse volunteerDataDTO = parseVolunteerRecommendListResponse(jsonContent);
            log.info("成功加载缓存推荐数据，会话ID: {}, 数据大小: {} bytes", chatSessionId, jsonContent.length());
            return volunteerDataDTO;
        } catch (Exception e) {
            log.error("解析本地缓存推荐JSON文件失败，会话ID: {}, 文件路径: {}", chatSessionId, localFilePath, e);
            throw new BusinessException(110, "解析缓存推荐数据文件失败");
        }
    }

    public VolunteerRecommendListResponse loadFinalSubmitVolunteerData(Long chatSessionId) {
        // 1.先从本地对应目录里找
        String localFilePath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, VolunteerFileType.FINAL);
        File localFile = new File(localFilePath);

        // 如果本地文件不存在，从OSS下载
        if (!localFile.exists()) {
            log.info("本地文件不存在，尝试从OSS下载，会话ID: {}, 本地路径: {}", chatSessionId, localFilePath);

            // 基于上传时的规则拼接OSS文件名
            String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSessionId, VolunteerFileType.FINAL);

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
            VolunteerRecommendListResponse volunteerDataDTO = parseVolunteerRecommendListResponse(jsonContent);
            log.info("成功加载最终志愿数据，会话ID: {}, 数据大小: {} bytes", chatSessionId, jsonContent.length());
            return volunteerDataDTO;
        } catch (Exception e) {
            log.error("解析本地最终志愿JSON文件失败，会话ID: {}, 文件路径: {}", chatSessionId, localFilePath, e);
            throw new BusinessException(110, "解析最终志愿数据文件失败");
        }
    }

    public VolunteerRecommendListResponse loadOriginalVolunteerData(Long chatSessionId) {
        String localFilePath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, VolunteerFileType.ORIGINAL);
        File localFile = new File(localFilePath);

        if (!localFile.exists()) {
            log.info("本地原始志愿文件不存在，尝试从OSS下载，会话ID: {}, 本地路径: {}", chatSessionId, localFilePath);
            String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSessionId, VolunteerFileType.ORIGINAL);
            boolean downloadSuccess = aliOSSService.downloadFile(ossFileName, localFilePath);
            if (!downloadSuccess) {
                log.error("从OSS下载原始志愿文件失败，会话ID: {}, OSS文件名: {}", chatSessionId, ossFileName);
                throw new BusinessException(110, "下载原始志愿数据文件失败");
            }
            log.info("从OSS下载原始志愿文件成功，会话ID: {}, 本地路径: {}", chatSessionId, localFilePath);
        }

        try {
            String jsonContent = FileUtils.readFileToString(localFile, StandardCharsets.UTF_8);
            VolunteerRecommendListResponse volunteerDataDTO = parseVolunteerRecommendListResponse(jsonContent);
            log.info("成功加载原始志愿数据，会话ID: {}, 数据大小: {} bytes", chatSessionId, jsonContent.length());
            return volunteerDataDTO;
        } catch (Exception e) {
            log.error("解析本地原始志愿JSON文件失败，会话ID: {}, 文件路径: {}", chatSessionId, localFilePath, e);
            throw new BusinessException(110, "解析原始志愿数据文件失败");
        }
    }

    VolunteerRecommendListResponse parseVolunteerRecommendListResponse(String jsonContent) {
        VolunteerRecommendListResponse response = JSONObject.parseObject(jsonContent, VolunteerRecommendListResponse.class);
        if (hasRecommendListItems(response)) {
            return response;
        }
        VolunteerDataDTO legacyData = JSONObject.parseObject(jsonContent, VolunteerDataDTO.class);
        if (legacyData == null || legacyData.getDetailList() == null || legacyData.getDetailList().isEmpty()) {
            return response;
        }
        return convertLegacyVolunteerData(legacyData);
    }

    private boolean hasRecommendListItems(VolunteerRecommendListResponse response) {
        return response != null
                && ((response.getSprints() != null && !response.getSprints().isEmpty())
                || (response.getSafes() != null && !response.getSafes().isEmpty())
                || (response.getProtects() != null && !response.getProtects().isEmpty()));
    }

    private VolunteerRecommendListResponse convertLegacyVolunteerData(VolunteerDataDTO legacyData) {
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(convertLegacyBaseData(legacyData));
        response.setSprints(new ArrayList<>());
        response.setSafes(new ArrayList<>());
        response.setProtects(new ArrayList<>());

        Map<String, Integer> tierRanks = new HashMap<>();
        for (ProgramPageDTO.SchoolDetail detail : legacyData.getDetailList()) {
            if (detail == null) {
                continue;
            }
            String tier = normalizeLegacyTier(detail.getVolunteerLevel());
            VolunteerRecommendListResponse.VolunteerSchool school = convertLegacySchool(detail);
            Integer rank = tierRanks.getOrDefault(tier, 0) + 1;
            tierRanks.put(tier, rank);
            school.setRank_in_tier(rank);
            if ("冲".equals(tier)) {
                response.getSprints().add(school);
            } else if ("稳".equals(tier)) {
                response.getSafes().add(school);
            } else {
                response.getProtects().add(school);
            }
        }
        return response;
    }

    private VolunteerRecommendListResponse.BaseData convertLegacyBaseData(VolunteerDataDTO legacyData) {
        VolunteerRecommendListResponse.BaseData baseData = new VolunteerRecommendListResponse.BaseData();
        ProgramPageDTO.ProgramModel model = legacyData == null ? null : legacyData.getModel();
        if (model == null) {
            return baseData;
        }
        Integer total = firstNotNull(model.getMajorTotalNum(), model.getSchoolTotalNum());
        baseData.setTotal_count(total);
        baseData.setNeed_count(total);
        Map<String, Integer> targetCounts = new HashMap<>();
        targetCounts.put("sprints_count", firstNotNull(model.getMajorSprintNum(), model.getSchoolSprintNum(), 0));
        targetCounts.put("safes_count", firstNotNull(model.getMajorSafeNum(), model.getSchoolSafeNum(), 0));
        targetCounts.put("protects_count", firstNotNull(model.getMajorProtectNum(), model.getSchoolProtectNum(), 0));
        baseData.setThree_target_count_map(targetCounts);
        return baseData;
    }

    private VolunteerRecommendListResponse.VolunteerSchool convertLegacySchool(ProgramPageDTO.SchoolDetail detail) {
        VolunteerRecommendListResponse.VolunteerSchool school = new VolunteerRecommendListResponse.VolunteerSchool();
        school.setPlanSchoolDataId(detail.getPlanSchoolDataId());
        school.setSchoolId(detail.getSchoolId());
        school.setSchoolUnitCode(detail.getSchoolUnitCode());
        school.setSchool_name(detail.getSchoolUnitName());
        school.setEnroll_ratio(detail.getEnrollRatio());
        school.setLevel(normalizeLegacyTier(detail.getVolunteerLevel()));
        school.setSchool_rank(detail.getXyhRank());
        if (detail.getArea() != null) {
            school.setProvince_name(detail.getArea().getData());
        }
        if (detail.getCity() != null) {
            school.setCity_name(detail.getCity().getData());
        }
        if (detail.getLevel() != null) {
            school.setSchool_level(detail.getLevel().getDesc());
        }
        if (detail.getType() != null) {
            school.setSchool_category(detail.getType().getData());
        }
        school.setMajors(convertLegacyMajors(detail));
        // selectSchool/selectZy belongs to the upstream full-data selection model, not to
        // assistant preferred-plan semantics. Keep original files as candidate sources only.
        school.setIs_preferred(false);
        return school;
    }

    private List<VolunteerRecommendListResponse.VolunteerMajor> convertLegacyMajors(ProgramPageDTO.SchoolDetail detail) {
        List<VolunteerRecommendListResponse.VolunteerMajor> majors = new ArrayList<>();
        if (detail.getMajorVOList() != null && !detail.getMajorVOList().isEmpty()) {
            for (ProgramPageDTO.MajorVO majorVO : detail.getMajorVOList()) {
                if (majorVO == null) {
                    continue;
                }
                VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
                major.setPlanMajorDataId(majorVO.getPlanMajorDataId());
                major.setMajorId(majorVO.getMajorId());
                major.setMajor_name(majorVO.getMajorName());
                major.setMajorUnitCode(majorVO.getUnitCode());
                major.setCategoryId(majorVO.getCategoryId());
                major.setSubCategoryId(majorVO.getSubCategoryId());
                major.setEnroll_ratio(majorVO.getEnrollRatio());
                major.setLevel(normalizeLegacyTier(majorVO.getVolunteerLevel()));
                major.setPlanNum(majorVO.getPlanNum());
                major.setPlanMoney(majorVO.getMoney());
                major.setDuration(majorVO.getDuration());
                major.setMust_subject(majorVO.getSelectInfo() == null ? Collections.emptyList() : Collections.singletonList(majorVO.getSelectInfo()));
                major.getAlgTagMap().put("legacy_select_zy", Boolean.TRUE.equals(majorVO.getSelectZy()));
                majors.add(major);
            }
            return majors;
        }
        VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
        major.setPlanMajorDataId(detail.getPlanMajorDataId());
        major.setMajorId(detail.getMajorId());
        major.setMajor_name(detail.getMajorUnitName());
        major.setMajorUnitCode(detail.getMajorUnitCode());
        major.setCategoryId(detail.getCategoryId());
        major.setSubCategoryId(detail.getSubCategoryId());
        major.setEnroll_ratio(detail.getEnrollRatio());
        major.setLevel(normalizeLegacyTier(detail.getVolunteerLevel()));
        major.setPlanNum(detail.getPlanNum());
        major.setPlanMoney(detail.getPlanMoney());
        major.setDuration(detail.getPlanDuration());
        major.setMust_subject(detail.getSelectInfo() == null ? Collections.emptyList() : Collections.singletonList(detail.getSelectInfo()));
        majors.add(major);
        return majors;
    }

    private String normalizeLegacyTier(ProgramPageDTO.Type type) {
        if (type == null || type.getCode() == null) {
            return "保";
        }
        if ("SPRINT".equalsIgnoreCase(type.getCode())) {
            return "冲";
        }
        if ("SAFE".equalsIgnoreCase(type.getCode())) {
            return "稳";
        }
        return "保";
    }

    @SafeVarargs
    private final <T> T firstNotNull(T... values) {
        if (values == null) {
            return null;
        }
        for (T value : values) {
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    /**
     * 提交志愿列表
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @return 提交响应
     */
    public Boolean submitVolunteerList(Long tenantId, Long chatSessionId) {
        log.info("submitVolunteerList: tenantId={}, chatSessionId={}", tenantId, chatSessionId);

        VolunteerRecommendListResponse volunteerRecommendListResponse = this.doRecommendVolunteerList(tenantId, chatSessionId, true);

        //截断后的结果上传写入本地文件，然后上传oss

        // 1.全量数据形成文件，本机存一份，文件存储到/tmpdata/session_volunteer_{chatSessionId}_final.json
        String filePath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, VolunteerFileType.FINAL);
        try {
            FileUtils.writeStringToFile(new File(filePath), JSON.toJSONString(volunteerRecommendListResponse), StandardCharsets.UTF_8);
        } catch (IOException e) {
            log.error("保存本地文件失败，文件路径: {}", filePath, e);
            throw new BusinessException(110, "加载志愿数据失败");
        }

        // 2.将文件存储到oss
        try {
            String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSessionId, VolunteerFileType.FINAL);
            String etag = aliOSSService.uploadFile(ossFileName, new File(filePath));
            log.info("文件上传到OSS成功，文件名: {}, ETag: {}", ossFileName, etag);
        } catch (Exception e) {
            log.error("文件上传到OSS失败，文件路径: {}", filePath, e);
            throw new BusinessException(110, "保持最终志愿数据失败");
        }

        // 2.5 生成并保存摘要文件
        savePlanSummary(chatSessionId, volunteerRecommendListResponse, VolunteerFileType.FINAL_SUMMARY);

        //3.更新会话状态
        ChatSession chatSessionUp = new ChatSession();
        chatSessionUp.setId(chatSessionId);
        chatSessionUp.setEndTime(new Date());
        chatSessionUp.setSessionStatus(SessionStatus.FINISHED);
        chatSessionSharedService.updateById(chatSessionUp);
        //更新
        chatSessionExtraDataSharedService.saveOrUpdateSessionStatus(chatSessionUp.getId(), chatSessionUp.getSessionStatus());

        return Boolean.TRUE;
    }

    /**
     * Excel导出结果包装类
     */
    public static class ExcelExportResult {
        private byte[] excelData;
        private String fileName;

        public ExcelExportResult(byte[] excelData, String fileName) {
            this.excelData = excelData;
            this.fileName = fileName;
        }

        public byte[] getExcelData() {
            return excelData;
        }

        public String getFileName() {
            return fileName;
        }
    }

    /**
     * 导出志愿列表
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @return 导出响应（包含文件内容和文件名）
     */
    public ExcelExportResult exportVolunteerList(Long tenantId, Long chatSessionId) {
        log.info("exportVolunteerList: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        ChatSessionExtraData chatSessionExtraDataScore = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (chatSessionExtraDataScore == null) {
            throw new BusinessException(404, "用户分数信息不存在");
        }
        CreateSessionReq userScoreDetail = JSONObject.parseObject(chatSessionExtraDataScore.getDataValue(), CreateSessionReq.class);

        try {
            // 获取志愿推荐列表数据
            VolunteerRecommendListResponse volunteerData = recommendVolunteerList(tenantId, chatSessionId, true, false);

            // 转换为Excel数据格式（区分主列表和候补列表）
            VolunteerResponseBuilder.ExcelDataWrapper excelDataWrapper = responseBuilder.convertToExcelData(volunteerData);

            byte[] excelBytes;
            if (volunteerData.getMajorSchoolType()) {
                excelBytes = ExcelUtil.generateVolunteerExcel(userScoreDetail, excelDataWrapper.getMainList(), excelDataWrapper.getBackupList(), false);
            } else {
                excelBytes = ExcelUtil.generateVolunteerExcel(userScoreDetail, excelDataWrapper.getMainList(), excelDataWrapper.getBackupList(), true);
            }

            // 生成文件名：省份+分数+选科+日期
            String fileName = generateExcelFileName(userScoreDetail);

            return new ExcelExportResult(excelBytes, fileName);

        } catch (Exception e) {
            log.error("导出志愿列表失败", e);
            throw new RuntimeException("导出志愿列表失败", e);
        }
    }

    /**
     * 生成Excel文件名：省份+分数+选科+日期
     */
    private String generateExcelFileName(CreateSessionReq userScoreDetail) {
        List<String> parts = new ArrayList<>();

        // 省份
        if (userScoreDetail.getProvince() != null && userScoreDetail.getProvince().getName() != null) {
            parts.add(userScoreDetail.getProvince().getName());
        }

        // 分数
        if (userScoreDetail.getTotalScore() != null) {
            parts.add(userScoreDetail.getTotalScore() + "分");
        }

        // 选科
        String subjectStr = getSubjectString(userScoreDetail);
        if (subjectStr != null && !subjectStr.isEmpty()) {
            parts.add(subjectStr);
        }

        // 日期
        String dateStr = java.time.LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd"));
        parts.add(dateStr);

        // 组合文件名
        String fileName = String.join("_", parts) + ".xlsx";
        return fileName;
    }

    /**
     * 生成并保存方案摘要文件（轻量级元信息），同时上传到 OSS
     *
     * @param chatSessionId 会话ID
     * @param response      完整方案数据
     * @param fileType      摘要文件类型（TEMP_SUMMARY 或 FINAL_SUMMARY）
     */
    private void savePlanSummary(Long chatSessionId, VolunteerRecommendListResponse response, VolunteerFileType fileType) {
        try {
            VolunteerRecommendListResponse.BaseData baseData = response.getBaseData();
            if (baseData == null) {
                log.warn("savePlanSummary: baseData is null, skip summary generation for session {}", chatSessionId);
                return;
            }

            Map<String, Object> summary = new HashMap<>();
            summary.put("total_count", baseData.getTotal_count());
            summary.put("need_count", baseData.getNeed_count());
            summary.put("sprints_total", response.getSprints() != null ? response.getSprints().size() : 0);
            summary.put("safes_total", response.getSafes() != null ? response.getSafes().size() : 0);
            summary.put("protects_total", response.getProtects() != null ? response.getProtects().size() : 0);

            // 统计各层级优选数量
            summary.put("sprints_preferred", countPreferred(response.getSprints()));
            summary.put("safes_preferred", countPreferred(response.getSafes()));
            summary.put("protects_preferred", countPreferred(response.getProtects()));

            summary.put("sprints_enroll_ratio", baseData.getSprints_enroll_ratio());
            summary.put("safes_enroll_ratio", baseData.getSafes_enroll_ratio());
            summary.put("protects_enroll_ratio", baseData.getProtects_enroll_ratio());
            summary.put("user_info_summary", baseData.getUserInfoSummary());
            summary.put("volunteer_model", baseData.getVolunteerModel() != null ? baseData.getVolunteerModel().name() : null);
            summary.put("report_name", baseData.getReportName());

            String summaryJson = JSON.toJSONString(summary);

            // 保存到本地
            String localPath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, fileType);
            FileUtils.writeStringToFile(new File(localPath), summaryJson, StandardCharsets.UTF_8);
            log.info("方案摘要已保存到本地: {}", localPath);

            // 上传到OSS
            String ossPath = volunteerFilePathUtil.getOssFilePath(chatSessionId, fileType);
            String etag = aliOSSService.uploadFile(ossPath, new File(localPath));
            log.info("方案摘要已上传到OSS: {}, ETag: {}", ossPath, etag);
        } catch (Exception e) {
            log.error("savePlanSummary failed for session {}, fileType {}", chatSessionId, fileType, e);
        }
    }

    /**
     * 统计列表中优选志愿的数量
     */
    private int countPreferred(List<VolunteerRecommendListResponse.VolunteerSchool> schools) {
        if (schools == null) return 0;
        return (int) schools.stream().filter(s -> Boolean.TRUE.equals(s.getIs_preferred())).count();
    }

    /**
     * 获取选科字符串
     */
    private String getSubjectString(CreateSessionReq userScoreDetail) {
        if (userScoreDetail.getSubjectList() != null && !userScoreDetail.getSubjectList().isEmpty()) {
            List<String> subjectFobiddenList = Arrays.asList("08", "10", "11");
            List<String> subjects = userScoreDetail.getSubjectList().stream()
                    .filter(subject -> !subjectFobiddenList.contains(subject.getValue()))
                    .map(subject -> subject.getName())
                    .collect(java.util.stream.Collectors.toList());
            if (!subjects.isEmpty()) {
                return String.join(".", subjects);
            }
        }
        // 如果没有科目列表，使用科目类型
        if (userScoreDetail.getSubjectType() != null && userScoreDetail.getSubjectType().getDesc() != null) {
            return userScoreDetail.getSubjectType().getDesc();
        }
        return "";
    }
}
