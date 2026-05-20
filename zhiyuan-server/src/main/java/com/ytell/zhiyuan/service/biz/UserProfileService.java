package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.ProfileKVDto;
import com.ytell.zhiyuan.model.dto.UserBasicProfileResponse;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.UserIntentValueDetail;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.model.enums.UserIntentDimension;
import com.ytell.zhiyuan.model.enums.UserIntentEmotionLevel;
import com.ytell.zhiyuan.model.enums.UserIntentPolarity;
import com.ytell.zhiyuan.model.req.UserIntentEmotionSaveReq;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.collections4.CollectionUtils;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Consumer;
import java.util.stream.Collectors;

/**
 * 用户画像管理服务
 */
@Slf4j
@Service
public class UserProfileService {

    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;

    @Autowired
    private VolunteerUtils utils;
    @Autowired
    private VolunteerDataProvider dataProvider;
    @Autowired
    private PlanningStateService planningStateService;

    /**
     * 获取用户基本信息
     *
     * @param chatSessionId 会话ID
     * @return 用户基本信息响应
     */
    public UserBasicProfileResponse getUserBasicProfile(Long chatSessionId) {
        List<ProfileKVDto> userScore = Lists.newArrayList();
        List<ProfileKVDto> userBasic = Lists.newArrayList();

        //用户基本信息
        ChatSessionExtraData chatSessionExtraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (chatSessionExtraData == null) {
            return new UserBasicProfileResponse(userScore, userBasic);
        }

        CreateSessionReq createSessionReq;
        try {
            createSessionReq = JSONObject.parseObject(chatSessionExtraData.getDataValue(), CreateSessionReq.class);
        } catch (Exception e) {
            log.error("解析用户基本信息失败: chatSessionId={}", chatSessionId, e);
            return new UserBasicProfileResponse(userScore, userBasic);
        }

        // 分数信息
        if (createSessionReq.getTotalScore() != null) {
            userScore.add(new ProfileKVDto("总分", Lists.newArrayList(createSessionReq.getTotalScore())));
        }
        // 位次信息
        if (createSessionReq.getTotalScorePos() != null) {
            userScore.add(new ProfileKVDto("位次", Lists.newArrayList(createSessionReq.getTotalScorePos())));
        }

        // 各科分数
        if (createSessionReq.getSubjectScoreList() != null) {
            createSessionReq.getSubjectScoreList().forEach(score -> {
                if (score.getSubjectName() != null && score.getScore() != null) {
                    userScore.add(new ProfileKVDto(score.getSubjectName(), Lists.newArrayList(score.getScore())));
                }
            });
        }

        // 专项加分
        if (createSessionReq.getBonusPolicy() != null && createSessionReq.getBonusPolicy() && createSessionReq.getBonusScore() != null) {
            userScore.add(new ProfileKVDto("专项加分", Lists.newArrayList(createSessionReq.getBonusScore())));
        }
        //优势学科
        if (createSessionReq.getStrengthSubjectList() != null) {
            List<String> StrengthSubjects = createSessionReq.getStrengthSubjectList().stream().map(one -> one.getSubjectName()).collect(Collectors.toList());
            userScore.add(new ProfileKVDto("优势学科（自选）", Lists.newArrayList(StrengthSubjects)));
        }

        // 用户基本信息
        if (createSessionReq.getUserName() != null) {
            userBasic.add(new ProfileKVDto("昵称", Lists.newArrayList(createSessionReq.getUserName())));
        }
        if (createSessionReq.getSex() != null && createSessionReq.getSex().getName() != null) {
            userBasic.add(new ProfileKVDto("性别", Lists.newArrayList(createSessionReq.getSex().getName())));
        }
        if (createSessionReq.getProvince() != null && createSessionReq.getProvince().getName() != null) {
            userBasic.add(new ProfileKVDto("高考省份", Lists.newArrayList(createSessionReq.getProvince().getName())));
        }
        if (createSessionReq.getExamYear() != null) {
            userBasic.add(new ProfileKVDto("高考年份", Lists.newArrayList(createSessionReq.getExamYear())));
        }
        // 选科信息
        if (createSessionReq.getSubjectList() != null && !createSessionReq.getSubjectList().isEmpty()) {
            List<Object> subjects = Lists.newArrayList();
            createSessionReq.getSubjectList().forEach(subject -> {
                if (subject.getName() != null) {
                    subjects.add(subject.getName());
                }
            });
            if (!subjects.isEmpty()) {
                userBasic.add(new ProfileKVDto("选科", subjects));
            }
        }

        if (createSessionReq.getSpecialPlan() != null) {
            userBasic.add(new ProfileKVDto("专项填报资格", Lists.newArrayList(createSessionReq.getSpecialPlan() ? "是" : "否")));
        }
        if (createSessionReq.getColorBlindness() != null) {
            userBasic.add(new ProfileKVDto("色盲色弱", Lists.newArrayList(createSessionReq.getColorBlindness() ? "是" : "否")));
        } else {
            if (createSessionReq.getColorSituation() != null) {
                userBasic.add(new ProfileKVDto("色盲色弱", Lists.newArrayList(createSessionReq.getColorSituation().contains("normal") ? "否" : "是")));
            }
        }
        if (createSessionReq.getMinority() != null) {
            userBasic.add(new ProfileKVDto("少数民族", Lists.newArrayList(createSessionReq.getMinority() ? "是" : "否")));
        } else {
            if (createSessionReq.getEthnicity() != null && createSessionReq.getEthnicity().getCode() != null) {
                userBasic.add(new ProfileKVDto("少数民族", Lists.newArrayList("01".equals(createSessionReq.getEthnicity().getCode()) ? "否" : "是")));
            }
        }
        if (createSessionReq.getAcceptForeignSchool() != null){
            userBasic.add(new ProfileKVDto("考虑中外合作", Lists.newArrayList(createSessionReq.getAcceptForeignSchool() ? "是" : "否")));
        }

        return new UserBasicProfileResponse(userScore, userBasic);
    }


    /**
     * 获取用户意向信息
     *
     * @param chatSessionId 会话ID
     * @return 用户意向信息列表
     */
    public List<ProfileKVDto> userDynasticProfile(Long chatSessionId) {
        // 用户对话意向信息
        UserProfileData userDynasticProfileData = dataProvider.getUserProfileData(chatSessionId);

        //合并画像
        UserProfileData userProfileData = utils.mergeUserProfile(userDynasticProfileData);

        log.info("userProfileData:{}", JSONObject.toJSONString(userProfileData));
        // 获取用户批次等级，用于判断是本科还是专科
        String batchLevel = getBatchLevel(chatSessionId);

        List<ProfileKVDto> res = Lists.newArrayList();

        try {
            // 城市-省份
            List<String> positiveProvinces = userProfileData.getCity_info() != null ? userProfileData.getCity_info().getProvince() : Lists.newArrayList();
            List<String> negativeProvinces = userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getProvince() : Lists.newArrayList();
            if (!positiveProvinces.isEmpty() || !negativeProvinces.isEmpty()) {
                ProfileKVDto provinceDto = new ProfileKVDto();
                provinceDto.setName("地域-省份");
                provinceDto.setPDetails(buildIntentDetails(
                        userProfileData.getCity_info() != null ? userProfileData.getCity_info().getProvince() : null,
                        userProfileData.getCity_info() != null ? userProfileData.getCity_info().getProvince_code() : null,
                        userProfileData.getCity_info() != null ? userProfileData.getCity_info().getProvince_emotion() : null,
                        UserIntentDimension.CITY_PROVINCE,
                        UserIntentPolarity.POSITIVE));
                provinceDto.setNDetails(buildIntentDetails(
                        userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getProvince() : null,
                        userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getProvince_code() : null,
                        userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getProvince_emotion() : null,
                        UserIntentDimension.CITY_PROVINCE,
                        UserIntentPolarity.NEGATIVE));
                res.add(provinceDto);
            }

            // 城市-城市
            List<String> positiveCities = userProfileData.getCity_info() != null ? userProfileData.getCity_info().getCity() : Lists.newArrayList();
            List<String> negativeCities = userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getCity() : Lists.newArrayList();
            if (!positiveCities.isEmpty() || !negativeCities.isEmpty()) {
                ProfileKVDto cityDto = new ProfileKVDto();
                cityDto.setName("地域-城市");
                cityDto.setPDetails(buildIntentDetails(
                        userProfileData.getCity_info() != null ? userProfileData.getCity_info().getCity() : null,
                        userProfileData.getCity_info() != null ? userProfileData.getCity_info().getCity_code() : null,
                        userProfileData.getCity_info() != null ? userProfileData.getCity_info().getCity_emotion() : null,
                        UserIntentDimension.CITY_CITY,
                        UserIntentPolarity.POSITIVE));
                cityDto.setNDetails(buildIntentDetails(
                        userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getCity() : null,
                        userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getCity_code() : null,
                        userProfileData.getNegative_city_info() != null ? userProfileData.getNegative_city_info().getCity_emotion() : null,
                        UserIntentDimension.CITY_CITY,
                        UserIntentPolarity.NEGATIVE));
                res.add(cityDto);
            }

            // 院校
            List<String> positiveSchools = userProfileData.getCollege_info() != null ? userProfileData.getCollege_info().getValues() : Lists.newArrayList();
            List<String> negativeSchools = userProfileData.getNegative_college_info() != null ? userProfileData.getNegative_college_info().getValues() : Lists.newArrayList();
            if (!positiveSchools.isEmpty() || !negativeSchools.isEmpty()) {
                ProfileKVDto collegeDto = new ProfileKVDto();
                collegeDto.setName("院校");
                collegeDto.setPDetails(buildIntentDetails(
                        userProfileData.getCollege_info() != null ? userProfileData.getCollege_info().getValues() : null,
                        userProfileData.getCollege_info() != null ? userProfileData.getCollege_info().getValues_code() : null,
                        userProfileData.getCollege_info() != null ? userProfileData.getCollege_info().getValues_emotion() : null,
                        UserIntentDimension.COLLEGE,
                        UserIntentPolarity.POSITIVE));
                collegeDto.setNDetails(buildIntentDetails(
                        userProfileData.getNegative_college_info() != null ? userProfileData.getNegative_college_info().getValues() : null,
                        userProfileData.getNegative_college_info() != null ? userProfileData.getNegative_college_info().getValues_code() : null,
                        userProfileData.getNegative_college_info() != null ? userProfileData.getNegative_college_info().getValues_emotion() : null,
                        UserIntentDimension.COLLEGE,
                        UserIntentPolarity.NEGATIVE));
                res.add(collegeDto);
            }

            // 根据批次代码决定展示前缀及维度
            String majorPrefix = "专业";
            if ("01".equals(batchLevel)) {
                majorPrefix = "本科";
            } else if ("02".equals(batchLevel)) {
                majorPrefix = "专科";
            }
            addMajorIntent(res,
                    userProfileData,
                    majorPrefix,
                    UserIntentDimension.MAJOR_LEVEL2,
                    UserIntentDimension.MAJOR_LEVEL3);

            // 标签
            List<String> positiveTags = userProfileData.getTag_info() != null ? userProfileData.getTag_info().getValues() : Lists.newArrayList();
            List<String> negativeTags = userProfileData.getNegative_tag_info() != null ? userProfileData.getNegative_tag_info().getValues() : Lists.newArrayList();
            if (!positiveTags.isEmpty() || !negativeTags.isEmpty()) {
                ProfileKVDto tagDto = new ProfileKVDto();
                tagDto.setName("其他");
                tagDto.setPDetails(buildIntentDetails(
                        userProfileData.getTag_info() != null ? userProfileData.getTag_info().getValues() : null,
                        null,
                        userProfileData.getTag_info() != null ? userProfileData.getTag_info().getValues_emotion() : null,
                        UserIntentDimension.TAG,
                        UserIntentPolarity.POSITIVE));
                tagDto.setNDetails(buildIntentDetails(
                        userProfileData.getNegative_tag_info() != null ? userProfileData.getNegative_tag_info().getValues() : null,
                        null,
                        userProfileData.getNegative_tag_info() != null ? userProfileData.getNegative_tag_info().getValues_emotion() : null,
                        UserIntentDimension.TAG,
                        UserIntentPolarity.NEGATIVE));
                res.add(tagDto);
            }

        } catch (Exception e) {
            log.error("解析用户意向信息失败: chatSessionId={}", chatSessionId, e);
            return Lists.newArrayList();
        }

        return res;
    }

    /**
     * 获取用户批次代码
     *
     * @param chatSessionId 会话ID
     * @return 批次代码
     */
    private String getBatchLevel(Long chatSessionId) {
        try {
            ChatSessionExtraData scoreData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
            if (scoreData != null) {
                CreateSessionReq createSessionReq = JSONObject.parseObject(scoreData.getDataValue(), CreateSessionReq.class);
                if (createSessionReq.getBatch() != null && createSessionReq.getBatch().getCode() != null) {
                    return createSessionReq.getBatch().getLevel();
                }
            }
        } catch (Exception e) {
            log.error("获取用户批次信息失败: chatSessionId={}", chatSessionId, e);
        }
        return null;
    }

    /**
     * 添加专业意向信息
     *
     * @param res              结果列表
     * @param userProfileData  用户画像数据
     * @param prefix           展示前缀
     * @param level2Dimension  二级专业维度
     * @param level3Dimension  三级专业维度
     */
    private void addMajorIntent(List<ProfileKVDto> res,
                                UserProfileData userProfileData,
                                String prefix,
                                UserIntentDimension level2Dimension,
                                UserIntentDimension level3Dimension) {
        UserProfileData.MajorIntent positiveIntent = userProfileData.getMajor_intent();
        UserProfileData.MajorIntent negativeIntent = userProfileData.getNegative_major_intent();

        List<String> positiveLevel2 = positiveIntent != null ? positiveIntent.getLevel2() : Lists.newArrayList();
        List<String> negativeLevel2 = negativeIntent != null ? negativeIntent.getLevel2() : Lists.newArrayList();
        if (!positiveLevel2.isEmpty() || !negativeLevel2.isEmpty()) {
            ProfileKVDto level2Dto = new ProfileKVDto();
            level2Dto.setName(prefix + "专业类");
            level2Dto.setPDetails(buildIntentDetails(
                    positiveIntent != null ? positiveIntent.getLevel2() : null,
                    positiveIntent != null ? positiveIntent.getLevel2_code() : null,
                    positiveIntent != null ? positiveIntent.getLevel2_emotion() : null,
                    level2Dimension,
                    UserIntentPolarity.POSITIVE));
            level2Dto.setNDetails(buildIntentDetails(
                    negativeIntent != null ? negativeIntent.getLevel2() : null,
                    negativeIntent != null ? negativeIntent.getLevel2_code() : null,
                    negativeIntent != null ? negativeIntent.getLevel2_emotion() : null,
                    level2Dimension,
                    UserIntentPolarity.NEGATIVE));
            res.add(level2Dto);
        }

        List<String> positiveLevel3 = positiveIntent != null ? positiveIntent.getLevel3() : Lists.newArrayList();
        List<String> negativeLevel3 = negativeIntent != null ? negativeIntent.getLevel3() : Lists.newArrayList();
        if (!positiveLevel3.isEmpty() || !negativeLevel3.isEmpty()) {
            ProfileKVDto level3Dto = new ProfileKVDto();
            level3Dto.setName(prefix + "专业");
            level3Dto.setPDetails(buildIntentDetails(
                    positiveIntent != null ? positiveIntent.getLevel3() : null,
                    positiveIntent != null ? positiveIntent.getLevel3_code() : null,
                    positiveIntent != null ? positiveIntent.getLevel3_emotion() : null,
                    level3Dimension,
                    UserIntentPolarity.POSITIVE));
            level3Dto.setNDetails(buildIntentDetails(
                    negativeIntent != null ? negativeIntent.getLevel3() : null,
                    negativeIntent != null ? negativeIntent.getLevel3_code() : null,
                    negativeIntent != null ? negativeIntent.getLevel3_emotion() : null,
                    level3Dimension,
                    UserIntentPolarity.NEGATIVE));
            res.add(level3Dto);
        }
    }

    public Boolean saveUserIntentEmotion(UserIntentEmotionSaveReq req) {
        if (req == null || req.getChatSessionId() == null) {
            throw new BusinessException(400, "chatSessionId不能为空");
        }
        if (CollectionUtils.isEmpty(req.getIntents())) {
            throw new BusinessException(400, "情绪信息不能为空");
        }
        UserProfileData originProfile = dataProvider.getUserProfileData(req.getChatSessionId());
        if (originProfile == null) {
            throw new BusinessException(404, "用户画像不存在");
        }
        UserProfileData mergedProfile = utils.mergeUserProfile(originProfile);
        Map<IntentGroupKey, IntentCommandBatch> batches = normalizeCommands(req.getIntents());
        applyEmotionCommands(mergedProfile, batches);
        persistProfile(req.getChatSessionId(), mergedProfile);
        planningStateService.syncProfileStateFromLegacy(
                req.getChatSessionId(),
                dataProvider.getUserScoreDetail(req.getChatSessionId()),
                mergedProfile,
                true);
        return Boolean.TRUE;
    }

    private List<UserIntentValueDetail> buildIntentDetails(List<String> labels,
                                                           List<String> codes,
                                                           List<String> emotions,
                                                           UserIntentDimension dimension,
                                                           UserIntentPolarity polarity) {
        List<UserIntentValueDetail> details = Lists.newArrayList();
        if (labels == null || labels.isEmpty()) {
            return details;
        }
        for (int i = 0; i < labels.size(); i++) {
            String label = labels.get(i);
            if (label == null) {
                continue;
            }
            UserIntentValueDetail detail = new UserIntentValueDetail();
            detail.setDimension(dimension.getCode());
            detail.setPolarity(polarity.name());
            detail.setLabel(label);
            detail.setCode(getValueByIndex(codes, i));
            UserIntentEmotionLevel level = UserIntentEmotionLevel.safeFromValue(getValueByIndex(emotions, i));
            detail.setEmotion(level.getValue());
            detail.setEmotionDesc(level.getDesc());
            details.add(detail);
        }
        return details;
    }

    private String getValueByIndex(List<String> source, int index) {
        if (source == null || index < 0 || index >= source.size()) {
            return null;
        }
        return source.get(index);
    }

    private Map<IntentGroupKey, IntentCommandBatch> normalizeCommands(List<UserIntentEmotionSaveReq.IntentEmotionItem> items) {
        Map<IntentGroupKey, IntentCommandBatch> grouped = new LinkedHashMap<>();
        for (UserIntentEmotionSaveReq.IntentEmotionItem item : items) {
            UserIntentDimension dimension = UserIntentDimension.fromCode(item.getDimension());
            if (dimension == null) {
                throw new BusinessException(400, "未知的维度:" + item.getDimension());
            }
            UserIntentPolarity polarity = UserIntentPolarity.fromValue(item.getPolarity());
            if (polarity == null) {
                throw new BusinessException(400, "未知的正负向标识:" + item.getPolarity());
            }
            IntentGroupKey key = new IntentGroupKey(dimension, polarity);
            IntentCommandBatch batch = grouped.computeIfAbsent(key, k -> new IntentCommandBatch());

            if (Boolean.TRUE.equals(item.getDeleteAll())) {
                batch.setDeleteAll(true);
                continue;
            }

            if (StringUtils.isBlank(item.getLabel()) && StringUtils.isBlank(item.getCode())) {
                throw new BusinessException(400, "情绪条目缺少名称或编码");
            }

            boolean deleted = Boolean.TRUE.equals(item.getDeleted());
            String emotionValue = null;
            if (!deleted) {
                try {
                    emotionValue = UserIntentEmotionLevel.fromValue(item.getEmotion()).getValue();
                } catch (IllegalArgumentException ex) {
                    throw new BusinessException(400, "情绪值不合法:" + item.getEmotion());
                }
            }
            batch.getCommands().add(new IntentEmotionCommand(
                    dimension,
                    polarity,
                    StringUtils.trimToEmpty(item.getLabel()),
                    StringUtils.trimToNull(item.getCode()),
                    emotionValue,
                    deleted
            ));
        }
        return grouped;
    }

    private void applyEmotionCommands(UserProfileData profile, Map<IntentGroupKey, IntentCommandBatch> groupedCommands) {
        if (profile == null || groupedCommands == null || groupedCommands.isEmpty()) {
            return;
        }
        groupedCommands.forEach((key, batch) -> {
            IntentValueList intentList = loadIntentValueList(profile, key.dimension, key.polarity);
            if (intentList != null) {
                applyEmotionUpdates(intentList, batch);
            }
        });
    }

    private IntentValueList loadIntentValueList(UserProfileData profile, UserIntentDimension dimension, UserIntentPolarity polarity) {
        switch (dimension) {
            case CITY_PROVINCE:
                return buildCityIntentList(profile, polarity == UserIntentPolarity.POSITIVE, true);
            case CITY_CITY:
                return buildCityIntentList(profile, polarity == UserIntentPolarity.POSITIVE, false);
            case COLLEGE:
                return buildCollegeIntentList(profile, polarity == UserIntentPolarity.POSITIVE);
            case TAG:
                return buildTagIntentList(profile, polarity == UserIntentPolarity.POSITIVE);
            case MAJOR_LEVEL2:
                return buildMajorIntentList(profile, polarity == UserIntentPolarity.POSITIVE, true);
            case MAJOR_LEVEL3:
                return buildMajorIntentList(profile, polarity == UserIntentPolarity.POSITIVE, false);
            default:
                return null;
        }
    }

    private IntentValueList buildCityIntentList(UserProfileData profile, boolean positive, boolean province) {
        UserProfileData.CityInfo cityInfo = ensureCityInfo(profile, positive);
        List<String> labels = province ? cityInfo.getProvince() : cityInfo.getCity();
        List<String> codes = province ? cityInfo.getProvince_code() : cityInfo.getCity_code();
        List<String> emotions = province ? cityInfo.getProvince_emotion() : cityInfo.getCity_emotion();
        List<IntentValue> values = buildIntentValues(labels, codes, emotions);
        return new IntentValueList(values, updated -> writeCityValues(cityInfo, province, updated));
    }

    private IntentValueList buildCollegeIntentList(UserProfileData profile, boolean positive) {
        UserProfileData.CollegeInfo collegeInfo = ensureCollegeInfo(profile, positive);
        List<IntentValue> values = buildIntentValues(collegeInfo.getValues(), collegeInfo.getValues_code(), collegeInfo.getValues_emotion());
        return new IntentValueList(values, updated -> writeCollegeValues(collegeInfo, updated));
    }

    private IntentValueList buildTagIntentList(UserProfileData profile, boolean positive) {
        UserProfileData.TagInfo tagInfo = ensureTagInfo(profile, positive);
        List<IntentValue> values = buildIntentValues(tagInfo.getValues(), null, tagInfo.getValues_emotion());
        return new IntentValueList(values, updated -> writeTagValues(tagInfo, updated));
    }

    private IntentValueList buildMajorIntentList(UserProfileData profile, boolean positive, boolean level2) {
        UserProfileData.MajorIntent intent = ensureMajorIntent(profile, positive);
        List<String> labels = level2 ? intent.getLevel2() : intent.getLevel3();
        List<String> codes = level2 ? intent.getLevel2_code() : intent.getLevel3_code();
        List<String> emotions = level2 ? intent.getLevel2_emotion() : intent.getLevel3_emotion();
        List<IntentValue> values = buildIntentValues(labels, codes, emotions);
        return new IntentValueList(values, updated -> writeMajorValues(intent, level2, updated));
    }

    private UserProfileData.CityInfo ensureCityInfo(UserProfileData profile, boolean positive) {
        UserProfileData.CityInfo cityInfo = positive ? profile.getCity_info() : profile.getNegative_city_info();
        if (cityInfo == null) {
            cityInfo = new UserProfileData.CityInfo();
            if (positive) {
                profile.setCity_info(cityInfo);
            } else {
                profile.setNegative_city_info(cityInfo);
            }
        }
        return cityInfo;
    }

    private UserProfileData.CollegeInfo ensureCollegeInfo(UserProfileData profile, boolean positive) {
        UserProfileData.CollegeInfo collegeInfo = positive ? profile.getCollege_info() : profile.getNegative_college_info();
        if (collegeInfo == null) {
            collegeInfo = new UserProfileData.CollegeInfo();
            if (positive) {
                profile.setCollege_info(collegeInfo);
            } else {
                profile.setNegative_college_info(collegeInfo);
            }
        }
        return collegeInfo;
    }

    private UserProfileData.TagInfo ensureTagInfo(UserProfileData profile, boolean positive) {
        UserProfileData.TagInfo tagInfo = positive ? profile.getTag_info() : profile.getNegative_tag_info();
        if (tagInfo == null) {
            tagInfo = new UserProfileData.TagInfo();
            if (positive) {
                profile.setTag_info(tagInfo);
            } else {
                profile.setNegative_tag_info(tagInfo);
            }
        }
        return tagInfo;
    }

    private UserProfileData.MajorIntent ensureMajorIntent(UserProfileData profile, boolean positive) {
        UserProfileData.MajorIntent intent = positive ? profile.getMajor_intent() : profile.getNegative_major_intent();
        if (intent == null) {
            intent = new UserProfileData.MajorIntent();
            if (positive) {
                profile.setMajor_intent(intent);
            } else {
                profile.setNegative_major_intent(intent);
            }
        }
        return intent;
    }

    private List<IntentValue> buildIntentValues(List<String> labels, List<String> codes, List<String> emotions) {
        List<IntentValue> values = Lists.newArrayList();
        if (labels == null || labels.isEmpty()) {
            return values;
        }
        for (int i = 0; i < labels.size(); i++) {
            String label = labels.get(i);
            if (label == null) {
                continue;
            }
            String code = getValueByIndex(codes, i);
            String emotion = UserIntentEmotionLevel.safeFromValue(getValueByIndex(emotions, i)).getValue();
            values.add(new IntentValue(label, code, emotion));
        }
        return values;
    }

    private void writeCityValues(UserProfileData.CityInfo cityInfo, boolean province, List<IntentValue> values) {
        List<String> labels = extractLabels(values);
        List<String> codes = extractCodes(values);
        List<String> emotions = extractEmotions(values);
        if (province) {
            cityInfo.setProvince(labels);
            cityInfo.setProvince_code(codes);
            cityInfo.setProvince_emotion(emotions);
        } else {
            cityInfo.setCity(labels);
            cityInfo.setCity_code(codes);
            cityInfo.setCity_emotion(emotions);
        }
    }

    private void writeCollegeValues(UserProfileData.CollegeInfo collegeInfo, List<IntentValue> values) {
        collegeInfo.setValues(extractLabels(values));
        collegeInfo.setValues_code(extractCodes(values));
        collegeInfo.setValues_emotion(extractEmotions(values));
    }

    private void writeTagValues(UserProfileData.TagInfo tagInfo, List<IntentValue> values) {
        tagInfo.setValues(extractLabels(values));
        tagInfo.setValues_emotion(extractEmotions(values));
    }

    private void writeMajorValues(UserProfileData.MajorIntent intent, boolean level2, List<IntentValue> values) {
        List<String> labels = extractLabels(values);
        List<String> codes = extractCodes(values);
        List<String> emotions = extractEmotions(values);
        if (level2) {
            intent.setLevel2(labels);
            intent.setLevel2_code(codes);
            intent.setLevel2_emotion(emotions);
        } else {
            intent.setLevel3(labels);
            intent.setLevel3_code(codes);
            intent.setLevel3_emotion(emotions);
        }
    }

    private List<String> extractLabels(List<IntentValue> values) {
        return values.stream().map(IntentValue::getLabel).collect(Collectors.toList());
    }

    private List<String> extractCodes(List<IntentValue> values) {
        return values.stream().map(IntentValue::getCode).collect(Collectors.toList());
    }

    private List<String> extractEmotions(List<IntentValue> values) {
        return values.stream().map(IntentValue::getEmotion).collect(Collectors.toList());
    }

    private void applyEmotionUpdates(IntentValueList intentList, IntentCommandBatch batch) {
        if (intentList == null || batch == null) {
            return;
        }
        if (batch.isDeleteAll()) {
            intentList.clearAll();
        }
        List<IntentEmotionCommand> commands = batch.getCommands();
        if (!CollectionUtils.isEmpty(commands)) {
            validateDuplicateCommands(commands);
            for (IntentEmotionCommand command : commands) {
                int index = intentList.findIndex(command);
                if (command.deleted) {
                    intentList.remove(index);
                    continue;
                }
                if (index >= 0) {
                    intentList.setValue(index, command.label, command.code, command.emotion);
                } else {
                    if (StringUtils.isBlank(command.label)) {
                        throw new BusinessException(400, "新增意向必须提供名称");
                    }
                    intentList.addValue(command.label, command.code, command.emotion);
                }
            }
        }
        intentList.flush();
    }

    private void validateDuplicateCommands(List<IntentEmotionCommand> commands) {
        Set<String> keySet = new HashSet<>();
        for (IntentEmotionCommand command : commands) {
            if (command.deleted) {
                continue;
            }
            String key = buildMatchKey(command.code, command.label);
            if (!keySet.add(key)) {
                throw new BusinessException(400, "情绪条目重复:" + command.label);
            }
        }
    }

    private String buildMatchKey(String code, String label) {
        String codeKey = StringUtils.trimToNull(code);
        if (codeKey != null) {
            return codeKey.toLowerCase();
        }
        return StringUtils.trimToEmpty(label).toLowerCase();
    }

    private static class IntentGroupKey {
        private final UserIntentDimension dimension;
        private final UserIntentPolarity polarity;

        private IntentGroupKey(UserIntentDimension dimension, UserIntentPolarity polarity) {
            this.dimension = dimension;
            this.polarity = polarity;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) {
                return true;
            }
            if (o == null || getClass() != o.getClass()) {
                return false;
            }
            IntentGroupKey that = (IntentGroupKey) o;
            return dimension == that.dimension && polarity == that.polarity;
        }

        @Override
        public int hashCode() {
            return Objects.hash(dimension, polarity);
        }
    }

    private static class IntentCommandBatch {
        private boolean deleteAll;
        private final List<IntentEmotionCommand> commands = Lists.newArrayList();

        public boolean isDeleteAll() {
            return deleteAll;
        }

        public void setDeleteAll(boolean deleteAll) {
            this.deleteAll = deleteAll;
        }

        public List<IntentEmotionCommand> getCommands() {
            return commands;
        }
    }

    private static class IntentValue {
        private String label;
        private String code;
        private String emotion;

        private IntentValue(String label, String code, String emotion) {
            this.label = label;
            this.code = code;
            this.emotion = emotion;
        }

        public String getLabel() {
            return label;
        }

        public String getCode() {
            return code;
        }

        public String getEmotion() {
            return emotion;
        }

        public void setLabel(String label) {
            this.label = label;
        }

        public void setCode(String code) {
            this.code = code;
        }

        public void setEmotion(String emotion) {
            this.emotion = emotion;
        }
    }

    private static class IntentValueList {
        private final List<IntentValue> values;
        private final Consumer<List<IntentValue>> writer;

        private IntentValueList(List<IntentValue> values, Consumer<List<IntentValue>> writer) {
            this.values = values;
            this.writer = writer;
        }

        private void clearAll() {
            values.clear();
        }

        private int findIndex(IntentEmotionCommand command) {
            if (CollectionUtils.isEmpty(values)) {
                return -1;
            }
            String codeKey = StringUtils.trimToNull(command.code);
            if (codeKey != null) {
                for (int i = 0; i < values.size(); i++) {
                    if (codeKey.equalsIgnoreCase(StringUtils.trimToNull(values.get(i).getCode()))) {
                        return i;
                    }
                }
            }
            String labelKey = StringUtils.trimToEmpty(command.label).toLowerCase();
            if (StringUtils.isBlank(labelKey)) {
                return -1;
            }
            for (int i = 0; i < values.size(); i++) {
                if (labelKey.equals(StringUtils.trimToEmpty(values.get(i).getLabel()).toLowerCase())) {
                    return i;
                }
            }
            return -1;
        }

        private void setValue(int index, String label, String code, String emotion) {
            if (index < 0 || index >= values.size()) {
                return;
            }
            IntentValue current = values.get(index);
            if (StringUtils.isNotBlank(label)) {
                current.setLabel(label);
            }
            current.setCode(code);
            current.setEmotion(normalizeEmotion(emotion));
        }

        private void addValue(String label, String code, String emotion) {
            values.add(new IntentValue(label, code, normalizeEmotion(emotion)));
        }

        private void remove(int index) {
            if (index < 0 || index >= values.size()) {
                return;
            }
            values.remove(index);
        }

        private void flush() {
            writer.accept(values);
        }

        private String normalizeEmotion(String emotion) {
            return StringUtils.defaultIfBlank(emotion, UserIntentEmotionLevel.defaultValue());
        }
    }

    private void persistProfile(Long chatSessionId, UserProfileData userProfileData) {
        ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        if (extraData == null) {
            ChatSessionExtraData newData = new ChatSessionExtraData();
            newData.setChatSessionId(chatSessionId);
            newData.setDataKey(ChatSessionExtraDataConstants.USER_PROFILE_KEY);
            newData.setDataType(DataType.JSON_OBJECT);
            newData.setDataValue(JSONObject.toJSONString(userProfileData));
            chatSessionExtraDataSharedService.save(newData);
        } else {
            extraData.setDataValue(JSONObject.toJSONString(userProfileData));
            chatSessionExtraDataSharedService.updateById(extraData);
        }
    }

    private static class IntentEmotionCommand {
        private final UserIntentDimension dimension;
        private final UserIntentPolarity polarity;
        private final String label;
        private final String code;
        private final String emotion;
        private final boolean deleted;

        IntentEmotionCommand(UserIntentDimension dimension, UserIntentPolarity polarity, String label, String code, String emotion, boolean deleted) {
            this.dimension = dimension;
            this.polarity = polarity;
            this.label = label;
            this.code = code;
            this.emotion = emotion;
            this.deleted = deleted;
        }
    }
}
