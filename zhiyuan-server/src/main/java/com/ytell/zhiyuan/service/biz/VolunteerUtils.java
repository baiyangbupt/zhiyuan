package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Joiner;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.volunteer.HistoryRecordDTO;
import com.ytell.zhiyuan.model.enums.UserIntentEmotionLevel;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 志愿工具类
 * 提供志愿相关的公共工具方法
 */
@Slf4j
@Component
public class VolunteerUtils {

    /**
     * 整理用户画像数据
     * 初始化画像已经在创建会话阶段写入 userProfileData，这里只做冲突清理
     *
     * @param userProfileData 会话画像数据
     * @return 清理后的画像数据
     */
    public UserProfileData mergeUserProfile(UserProfileData userProfileData) {
        log.info("开始整理用户画像数据（单一来源）");

        if (userProfileData == null) {
            log.warn("用户画像数据为空");
            return new UserProfileData();
        }

        UserProfileData mergedProfile = new UserProfileData();

        UserProfileData.MajorIntent mergedPositiveMajorIntent = copyMajorIntent(userProfileData.getMajor_intent());
        UserProfileData.MajorIntent mergedNegativeMajorIntent = copyMajorIntent(userProfileData.getNegative_major_intent());

        // 确保所有 MajorIntent 的 emotion 列表长度与 value/code 列表一致
        alignMajorIntentEmotions(mergedPositiveMajorIntent);
        alignMajorIntentEmotions(mergedNegativeMajorIntent);

        mergedProfile.setMajor_intent(mergedPositiveMajorIntent);
        mergedProfile.setNegative_major_intent(mergedNegativeMajorIntent);

        removeMajorIntentNegativeFromPositive(mergedPositiveMajorIntent, mergedNegativeMajorIntent);

        UserProfileData.CollegeInfo mergedCollegeInfo = copyCollegeInfo(userProfileData.getCollege_info());
        UserProfileData.CollegeInfo mergedNegativeCollegeInfo = copyCollegeInfo(userProfileData.getNegative_college_info());
        
        // 确保 CollegeInfo 的 emotion 列表长度与 values/code 列表一致
        alignCollegeInfoEmotions(mergedCollegeInfo);
        alignCollegeInfoEmotions(mergedNegativeCollegeInfo);
        
        resolveCollegeConflicts(mergedCollegeInfo, mergedNegativeCollegeInfo);

        mergedProfile.setCollege_info(mergedCollegeInfo);
        mergedProfile.setNegative_college_info(mergedNegativeCollegeInfo);

        UserProfileData.TagInfo mergedTagInfo = copyTagInfo(userProfileData.getTag_info());
        UserProfileData.TagInfo mergedNegativeTagInfo = copyTagInfo(userProfileData.getNegative_tag_info());
        
        // 确保 TagInfo 的 emotion 列表长度与 values 列表一致
        alignTagInfoEmotions(mergedTagInfo);
        alignTagInfoEmotions(mergedNegativeTagInfo);
        
        resolveTagConflicts(mergedTagInfo, mergedNegativeTagInfo);

        mergedProfile.setTag_info(mergedTagInfo);
        mergedProfile.setNegative_tag_info(mergedNegativeTagInfo);

        UserProfileData.CityInfo mergedPositiveCity = copyCityInfo(userProfileData.getCity_info());
        UserProfileData.CityInfo mergedNegativeCity = copyCityInfo(userProfileData.getNegative_city_info());
        
        // 确保 CityInfo 的 emotion 列表长度与 province/city/code 列表一致
        alignCityInfoEmotions(mergedPositiveCity);
        alignCityInfoEmotions(mergedNegativeCity);
        
        resolveCityConflicts(mergedPositiveCity, mergedNegativeCity);

        mergedProfile.setCity_info(mergedPositiveCity);
        mergedProfile.setNegative_city_info(mergedNegativeCity);
        mergedProfile.setStrength_subject_info(copyStrengthSubjectInfo(userProfileData.getStrength_subject_info()));

        log.info("用户画像数据整理完成");

        return mergedProfile;
    }




    private void resolveCollegeConflicts(UserProfileData.CollegeInfo positive, UserProfileData.CollegeInfo negative) {
        if (positive == null || negative == null) {
            return;
        }
        List<String> originalValues = positive.getValues();
        List<String> originalEmotions = positive.getValues_emotion();
        positive.setValues_code(removeNegativeFromPositive(positive.getValues_code(), negative.getValues_code()));
        positive.setValues(removeNegativeFromPositive(positive.getValues(), negative.getValues()));
        positive.setValues_emotion(alignEmotionAfterRemoval(
                positive.getValues(),
                originalValues,
                originalEmotions
        ));
        // 确保 emotion 列表长度与 values/code 列表一致
        alignCollegeInfoEmotions(positive);
    }

    private void resolveTagConflicts(UserProfileData.TagInfo positive, UserProfileData.TagInfo negative) {
        if (positive == null || negative == null) {
            return;
        }
        List<String> originalValues = positive.getValues();
        List<String> originalEmotions = positive.getValues_emotion();
        positive.setValues(removeNegativeFromPositive(positive.getValues(), negative.getValues()));
        positive.setValues_emotion(alignEmotionAfterRemoval(
                positive.getValues(),
                originalValues,
                originalEmotions
        ));
        // 确保 emotion 列表长度与 values 列表一致
        alignTagInfoEmotions(positive);
    }

    private void resolveCityConflicts(UserProfileData.CityInfo positive, UserProfileData.CityInfo negative) {
        if (positive == null || negative == null) {
            return;
        }
        List<String> originalProvince = positive.getProvince();
        List<String> originalProvinceEmotion = positive.getProvince_emotion();
        List<String> originalCity = positive.getCity();
        List<String> originalCityEmotion = positive.getCity_emotion();
        positive.setProvince(removeNegativeFromPositive(positive.getProvince(), negative.getProvince()));
        positive.setCity(removeNegativeFromPositive(positive.getCity(), negative.getCity()));
        positive.setProvince_code(removeNegativeFromPositive(positive.getProvince_code(), negative.getProvince_code()));
        positive.setCity_code(removeNegativeFromPositive(positive.getCity_code(), negative.getCity_code()));
        positive.setProvince_emotion(alignEmotionAfterRemoval(
                positive.getProvince(),
                originalProvince,
                originalProvinceEmotion
        ));
        positive.setCity_emotion(alignEmotionAfterRemoval(
                positive.getCity(),
                originalCity,
                originalCityEmotion
        ));
        // 确保 emotion 列表长度与 province/city/code 列表一致
        alignCityInfoEmotions(positive);
    }

    private UserProfileData.MajorIntent copyMajorIntent(UserProfileData.MajorIntent source) {
        if (source == null) {
            return null;
        }
        UserProfileData.MajorIntent target = new UserProfileData.MajorIntent();
        target.setLevel1(copyStringList(source.getLevel1()));
        target.setLevel2(copyStringList(source.getLevel2()));
        target.setLevel3(copyStringList(source.getLevel3()));
        target.setLevel1_code(copyStringList(source.getLevel1_code()));
        target.setLevel2_code(copyStringList(source.getLevel2_code()));
        target.setLevel3_code(copyStringList(source.getLevel3_code()));
        target.setLevel1_emotion(copyStringList(source.getLevel1_emotion()));
        target.setLevel2_emotion(copyStringList(source.getLevel2_emotion()));
        target.setLevel3_emotion(copyStringList(source.getLevel3_emotion()));
        return target;
    }

    private UserProfileData.CollegeInfo copyCollegeInfo(UserProfileData.CollegeInfo source) {
        if (source == null) {
            return null;
        }
        UserProfileData.CollegeInfo target = new UserProfileData.CollegeInfo();
        target.setValues(copyStringList(source.getValues()));
        target.setValues_code(copyStringList(source.getValues_code()));
        target.setValues_emotion(copyStringList(source.getValues_emotion()));
        return target;
    }

    private UserProfileData.TagInfo copyTagInfo(UserProfileData.TagInfo source) {
        if (source == null) {
            return null;
        }
        UserProfileData.TagInfo target = new UserProfileData.TagInfo();
        target.setValues(copyStringList(source.getValues()));
        target.setValues_emotion(copyStringList(source.getValues_emotion()));
        return target;
    }

    private UserProfileData.CityInfo copyCityInfo(UserProfileData.CityInfo source) {
        if (source == null) {
            return null;
        }
        UserProfileData.CityInfo target = new UserProfileData.CityInfo();
        target.setProvince(copyStringList(source.getProvince()));
        target.setCity(copyStringList(source.getCity()));
        target.setProvince_code(copyStringList(source.getProvince_code()));
        target.setCity_code(copyStringList(source.getCity_code()));
        target.setProvince_emotion(copyStringList(source.getProvince_emotion()));
        target.setCity_emotion(copyStringList(source.getCity_emotion()));
        return target;
    }

    private UserProfileData.StrengthSubjectInfo copyStrengthSubjectInfo(UserProfileData.StrengthSubjectInfo source) {
        if (source == null) {
            return null;
        }
        UserProfileData.StrengthSubjectInfo target = new UserProfileData.StrengthSubjectInfo();
        target.setValues(copyStringList(source.getValues()));
        target.setValues_code(copyStringList(source.getValues_code()));
        target.setValues_emotion(copyStringList(source.getValues_emotion()));
        return target;
    }

    private List<String> copyStringList(List<String> source) {
        return source == null ? Lists.newArrayList() : Lists.newArrayList(source);
    }


    /**
     * 从正向列表中移除负向列表中的项目
     * 处理正向和负向列表的互斥关系
     *
     * @param positiveList 正向列表
     * @param negativeList 负向列表
     * @return 移除负向项目后的正向列表
     */
    public List<String> removeNegativeFromPositive(List<String> positiveList, List<String> negativeList) {
        if (positiveList == null || positiveList.isEmpty()) {
            return new ArrayList<>();
        }

        if (negativeList == null || negativeList.isEmpty()) {
            return new ArrayList<>(positiveList);
        }

        List<String> result = new ArrayList<>();
        for (String item : positiveList) {
            if (item != null && !negativeList.contains(item)) {
                result.add(item);
            }
        }

        return result;
    }

    /**
     * 从正向专业意向中移除负向专业意向
     * 处理正向和负向专业意向的互斥关系，直接修改正向意向对象
     *
     * @param positiveMajorIntent 正向专业意向（会被修改）
     * @param negativeMajorIntent 负向专业意向
     */
    private void removeMajorIntentNegativeFromPositive(UserProfileData.MajorIntent positiveMajorIntent, 
                                                       UserProfileData.MajorIntent negativeMajorIntent) {
        if (positiveMajorIntent == null || negativeMajorIntent == null) {
            return;
        }

        List<String> originalLevel1 = positiveMajorIntent.getLevel1();
        List<String> originalLevel2 = positiveMajorIntent.getLevel2();
        List<String> originalLevel3 = positiveMajorIntent.getLevel3();
        List<String> originalLevel1Emotion = positiveMajorIntent.getLevel1_emotion();
        List<String> originalLevel2Emotion = positiveMajorIntent.getLevel2_emotion();
        List<String> originalLevel3Emotion = positiveMajorIntent.getLevel3_emotion();

        // 处理各个层级的专业名称和代码
        positiveMajorIntent.setLevel1(removeNegativeFromPositive(originalLevel1, negativeMajorIntent.getLevel1()));
        positiveMajorIntent.setLevel2(removeNegativeFromPositive(originalLevel2, negativeMajorIntent.getLevel2()));
        positiveMajorIntent.setLevel3(removeNegativeFromPositive(originalLevel3, negativeMajorIntent.getLevel3()));
        positiveMajorIntent.setLevel1_code(removeNegativeFromPositive(positiveMajorIntent.getLevel1_code(), negativeMajorIntent.getLevel1_code()));
        positiveMajorIntent.setLevel2_code(removeNegativeFromPositive(positiveMajorIntent.getLevel2_code(), negativeMajorIntent.getLevel2_code()));
        positiveMajorIntent.setLevel3_code(removeNegativeFromPositive(positiveMajorIntent.getLevel3_code(), negativeMajorIntent.getLevel3_code()));
        
        positiveMajorIntent.setLevel1_emotion(alignEmotionAfterRemoval(
                positiveMajorIntent.getLevel1(),
                originalLevel1,
                originalLevel1Emotion
        ));
        positiveMajorIntent.setLevel2_emotion(alignEmotionAfterRemoval(
                positiveMajorIntent.getLevel2(),
                originalLevel2,
                originalLevel2Emotion
        ));
        positiveMajorIntent.setLevel3_emotion(alignEmotionAfterRemoval(
                positiveMajorIntent.getLevel3(),
                originalLevel3,
                originalLevel3Emotion
        ));
        
        // 确保 emotion 列表长度与 value/code 列表一致
        alignMajorIntentEmotions(positiveMajorIntent);
        
        log.debug("从正向专业意向中移除负向专业意向完成");
    }

    /**
     * 清理专业名称中的括号内容
     * 例如：
     * "航空航天类(民用航空)(含飞行器设计与工程、飞行器控制与信息工程、低空技术与工程专业；专业分流时，100%类内专业任选)" -> "航空航天类"
     * "软件工程(AI交叉复合型创新人才培养实验班)" -> "软件工程"
     *
     * @param majorName 原始专业名称
     * @return 清理后的专业名称
     */
    public String removeBracketsFromMajorName(String majorName) {
        if (majorName == null || majorName.trim().isEmpty()) {
            return majorName;
        }

        // 移除所有括号及其内容（包括中文括号和英文括号）
        String cleanName = majorName.replaceAll("[\\(（][^\\)）]*[\\)）]", "").trim();

        return cleanName;
    }

    /**
     * 将志愿等级英文转换为中文
     *
     * @param englishLevel 英文等级 (SPRINT/SAFE/PROTECT)
     * @return 中文等级 (冲/稳/保)
     */
    public String convertVolunteerLevelToChinese(String englishLevel) {
        if (englishLevel == null) {
            return "";
        }
        switch (englishLevel.toUpperCase()) {
            case "SPRINT":
                return "冲";
            case "SAFE":
                return "稳";
            case "PROTECT":
                return "保";
            default:
                return englishLevel; // 如果不是已知的英文等级，返回原值
        }
    }

    /**
     * 构建历史分数列表（使用简化的 HistoryRecordDTO）
     *
     * @param historyRecords 历史记录列表
     * @return 历史分数列表
     */
    public List<VolunteerRecommendListResponse.HistoryScore> buildHistoryScoreList(List<HistoryRecordDTO> historyRecords) {
        List<VolunteerRecommendListResponse.HistoryScore> historyScores = new ArrayList<>();
        if (historyRecords != null && !historyRecords.isEmpty()) {
            for (HistoryRecordDTO record : historyRecords) {
                VolunteerRecommendListResponse.HistoryScore historyScore = new VolunteerRecommendListResponse.HistoryScore();

                // 设置年份
                if (record.getYear() != null) {
                    try {
                        historyScore.setYear(Integer.parseInt(record.getYear()));
                    } catch (NumberFormatException e) {
                        // 如果年份解析失败，使用默认值表示未知
                        historyScore.setYear(-1);
                    }
                }

                // 设置分数信息
                if (record.getScore() != null && !record.getScore().isEmpty()) {
                    try {
                        int score = Integer.parseInt(record.getScore());
                        historyScore.setScore(score);
                    } catch (NumberFormatException e) {
                        historyScore.setScore(-1);
                    }
                } else {
                    historyScore.setScore(-1);
                }

                //设置位次
                if (record.getPos() != null && !record.getPos().isEmpty()) {
                    try {
                        int pos = Integer.parseInt(record.getPos());
                        historyScore.setPos(pos);
                    } catch (NumberFormatException e) {
                        historyScore.setPos(-1);
                    }
                } else {
                    historyScore.setPos(-1);
                }

                //设置计划数量
                if (record.getPlanNum() != null && !record.getPlanNum().isEmpty()) {
                    try {
                        int planNum = Integer.parseInt(record.getPlanNum());
                        historyScore.setPlanNum(planNum);
                    } catch (NumberFormatException e) {
                        historyScore.setPlanNum(-1);
                    }
                } else {
                    historyScore.setPlanNum(-1);
                }

                //设置录取数量
                if (record.getEnrollNum() != null && !record.getEnrollNum().isEmpty()) {
                    try {
                        int enrollNum = Integer.parseInt(record.getEnrollNum());
                        historyScore.setEnrollNum(enrollNum);
                    } catch (NumberFormatException e) {
                        historyScore.setEnrollNum(-1);
                    }
                } else {
                    historyScore.setEnrollNum(-1);
                }

                if (historyScore.getYear() != null) {
                    historyScores.add(historyScore);
                }
            }
        }
        return historyScores;
    }

    /**
     * 获取会话额外数据摘要
     */
    public String getSessionExtraSummaryData(CreateSessionReq scoreInfo) {
        try {
            // "批次/省份/选科/分数/位次"
            String batch = scoreInfo.getBatch().getName();
            String province = scoreInfo.getProvince().getName();
            List<String> subjectFobiddenList = Lists.newArrayList("08", "10", "11");
            List<String> subjects = scoreInfo.getSubjectList().stream()
                    .filter(subject -> !subjectFobiddenList.contains(subject.getValue()))
                    .map(subject -> subject.getName())
                    .collect(Collectors.toList());
            String subjectStr = Joiner.on(".").join(subjects);
            Integer score = scoreInfo.getTotalScore();
            Integer pos = scoreInfo.getTotalScorePos();
            List<String> tags = Lists.newArrayList();
            if (!Strings.isNullOrEmpty(batch)) {
                tags.add(batch);
            }
            if (!Strings.isNullOrEmpty(province)) {
                tags.add(province);
            }
            if (!Strings.isNullOrEmpty(subjectStr)) {
                tags.add(subjectStr);
            }else{
               String subject= scoreInfo.getSubjectType().getDesc();
                tags.add(subject);
            }
            if (score != null) {
                tags.add(score+"分");
            }
            if (pos != null) {
                tags.add(pos+"名");
            }
            return Joiner.on("/").join(tags).trim();
        } catch (Exception e) {
            return "";
        }
    }

    /**
     * 处理数字值为空的情况
     */
    public String emptyNumValue(String val) {
        if (val.equals("-1")) {
            return "-";
        }
        return val;
    }

    private List<String> buildEmotionListForMergedValues(List<String> mergedValues,
                                                         List<String> priorityValues,
                                                         List<String> priorityEmotions,
                                                         List<String> secondaryValues,
                                                         List<String> secondaryEmotions) {
        if (mergedValues == null || mergedValues.isEmpty()) {
            return Lists.newArrayList();
        }
        List<String> result = Lists.newArrayListWithCapacity(mergedValues.size());
        for (String value : mergedValues) {
            String emotion = findEmotionForValue(value, priorityValues, priorityEmotions);
            if (Strings.isNullOrEmpty(emotion)) {
                emotion = findEmotionForValue(value, secondaryValues, secondaryEmotions);
            }
            result.add(Strings.isNullOrEmpty(emotion) ? UserIntentEmotionLevel.defaultValue() : emotion);
        }
        return result;
    }

    private String findEmotionForValue(String targetValue, List<String> values, List<String> emotions) {
        if (targetValue == null || values == null || values.isEmpty()) {
            return null;
        }
        for (int i = 0; i < values.size(); i++) {
            String value = values.get(i);
            if (targetValue.equals(value)) {
                if (emotions != null && i < emotions.size()) {
                    return emotions.get(i);
                }
                return null;
            }
        }
        return null;
    }

    private List<String> alignEmotionAfterRemoval(List<String> retainedValues,
                                                  List<String> originalValues,
                                                  List<String> originalEmotions) {
        if (retainedValues == null || retainedValues.isEmpty()) {
            return Lists.newArrayList();
        }
        return buildEmotionListForMergedValues(retainedValues, originalValues, originalEmotions, null, null);
    }

    /**
     * 对齐 MajorIntent 的 emotion 列表，确保与 value/code 列表长度一致
     * 对于每个层级，优先使用 value 列表的长度，如果 value 为空则使用 code 列表的长度
     * 如果某个位置没有 emotion，则设置为默认的 Strong 级别
     *
     * @param majorIntent 专业意向对象
     */
    private void alignMajorIntentEmotions(UserProfileData.MajorIntent majorIntent) {
        if (majorIntent == null) {
            return;
        }
        
        // 对齐 level1
        List<String> level1 = majorIntent.getLevel1();
        List<String> level1Code = majorIntent.getLevel1_code();
        List<String> level1Emotion = majorIntent.getLevel1_emotion();
        int level1Size = (level1 != null && !level1.isEmpty()) ? level1.size() : 
                        ((level1Code != null && !level1Code.isEmpty()) ? level1Code.size() : 0);
        if (level1Size > 0) {
            majorIntent.setLevel1_emotion(alignEmotionList(level1Emotion, level1Size, level1, level1Code));
        } else {
            majorIntent.setLevel1_emotion(Lists.newArrayList());
        }
        
        // 对齐 level2
        List<String> level2 = majorIntent.getLevel2();
        List<String> level2Code = majorIntent.getLevel2_code();
        List<String> level2Emotion = majorIntent.getLevel2_emotion();
        int level2Size = (level2 != null && !level2.isEmpty()) ? level2.size() : 
                        ((level2Code != null && !level2Code.isEmpty()) ? level2Code.size() : 0);
        if (level2Size > 0) {
            majorIntent.setLevel2_emotion(alignEmotionList(level2Emotion, level2Size, level2, level2Code));
        } else {
            majorIntent.setLevel2_emotion(Lists.newArrayList());
        }
        
        // 对齐 level3
        List<String> level3 = majorIntent.getLevel3();
        List<String> level3Code = majorIntent.getLevel3_code();
        List<String> level3Emotion = majorIntent.getLevel3_emotion();
        int level3Size = (level3 != null && !level3.isEmpty()) ? level3.size() : 
                        ((level3Code != null && !level3Code.isEmpty()) ? level3Code.size() : 0);
        if (level3Size > 0) {
            majorIntent.setLevel3_emotion(alignEmotionList(level3Emotion, level3Size, level3, level3Code));
        } else {
            majorIntent.setLevel3_emotion(Lists.newArrayList());
        }
    }

    /**
     * 对齐 CollegeInfo 的 emotion 列表，确保与 values/code 列表长度一致
     * 优先使用 values 列表的长度，如果 values 为空则使用 code 列表的长度
     * 如果某个位置没有 emotion，则设置为默认的 Strong 级别
     *
     * @param collegeInfo 院校信息对象
     */
    private void alignCollegeInfoEmotions(UserProfileData.CollegeInfo collegeInfo) {
        if (collegeInfo == null) {
            return;
        }
        
        List<String> values = collegeInfo.getValues();
        List<String> valuesCode = collegeInfo.getValues_code();
        List<String> valuesEmotion = collegeInfo.getValues_emotion();
        int size = (values != null && !values.isEmpty()) ? values.size() : 
                  ((valuesCode != null && !valuesCode.isEmpty()) ? valuesCode.size() : 0);
        
        if (size > 0) {
            collegeInfo.setValues_emotion(alignEmotionList(valuesEmotion, size, values, valuesCode));
        } else {
            collegeInfo.setValues_emotion(Lists.newArrayList());
        }
    }

    /**
     * 对齐 TagInfo 的 emotion 列表，确保与 values 列表长度一致
     * 如果某个位置没有 emotion，则设置为默认的 Strong 级别
     *
     * @param tagInfo 标签信息对象
     */
    private void alignTagInfoEmotions(UserProfileData.TagInfo tagInfo) {
        if (tagInfo == null) {
            return;
        }
        
        List<String> values = tagInfo.getValues();
        List<String> valuesEmotion = tagInfo.getValues_emotion();
        int size = (values != null && !values.isEmpty()) ? values.size() : 0;
        
        if (size > 0) {
            tagInfo.setValues_emotion(alignEmotionList(valuesEmotion, size, values, null));
        } else {
            tagInfo.setValues_emotion(Lists.newArrayList());
        }
    }

    /**
     * 对齐 CityInfo 的 emotion 列表，确保与 province/city/code 列表长度一致
     * 如果某个位置没有 emotion，则设置为默认的 Strong 级别
     *
     * @param cityInfo 城市信息对象
     */
    private void alignCityInfoEmotions(UserProfileData.CityInfo cityInfo) {
        if (cityInfo == null) {
            return;
        }
        
        // 对齐 province_emotion
        List<String> province = cityInfo.getProvince();
        List<String> provinceCode = cityInfo.getProvince_code();
        List<String> provinceEmotion = cityInfo.getProvince_emotion();
        int provinceSize = (province != null && !province.isEmpty()) ? province.size() : 
                          ((provinceCode != null && !provinceCode.isEmpty()) ? provinceCode.size() : 0);
        if (provinceSize > 0) {
            cityInfo.setProvince_emotion(alignEmotionList(provinceEmotion, provinceSize, province, provinceCode));
        } else {
            cityInfo.setProvince_emotion(Lists.newArrayList());
        }
        
        // 对齐 city_emotion
        List<String> city = cityInfo.getCity();
        List<String> cityCode = cityInfo.getCity_code();
        List<String> cityEmotion = cityInfo.getCity_emotion();
        int citySize = (city != null && !city.isEmpty()) ? city.size() : 
                      ((cityCode != null && !cityCode.isEmpty()) ? cityCode.size() : 0);
        if (citySize > 0) {
            cityInfo.setCity_emotion(alignEmotionList(cityEmotion, citySize, city, cityCode));
        } else {
            cityInfo.setCity_emotion(Lists.newArrayList());
        }
    }

    /**
     * 对齐 emotion 列表，确保长度与目标列表一致
     * 根据 value 列表或 code 列表来匹配已有的 emotion，如果找不到则使用默认值
     *
     * @param emotionList 现有的 emotion 列表
     * @param targetSize 目标长度
     * @param valueList 值列表（用于匹配）
     * @param codeList 代码列表（用于匹配，可选）
     * @return 对齐后的 emotion 列表
     */
    private List<String> alignEmotionList(List<String> emotionList, int targetSize, 
                                          List<String> valueList, List<String> codeList) {
        List<String> result = Lists.newArrayListWithCapacity(targetSize);
        String defaultValue = UserIntentEmotionLevel.defaultValue();
        
        for (int i = 0; i < targetSize; i++) {
            String emotion = null;
            
            // 优先从 value 列表中匹配 emotion
            if (valueList != null && i < valueList.size()) {
                String value = valueList.get(i);
                if (value != null) {
                    emotion = findEmotionByIndexOrValue(emotionList, valueList, value, i);
                    if (emotion == null && codeList != null && i < codeList.size()) {
                        String code = codeList.get(i);
                        if (code != null) {
                            emotion = findEmotionByIndexOrValue(emotionList, codeList, code, i);
                        }
                    }
                }
            } else if (codeList != null && i < codeList.size()) {
                // 如果 value 列表为空，则从 code 列表中匹配
                String code = codeList.get(i);
                if (code != null) {
                    emotion = findEmotionByIndexOrValue(emotionList, codeList, code, i);
                }
            }
            
            // 如果找不到对应的 emotion，使用默认值
            String finalEmotion = (emotion == null || emotion.isEmpty()) ? defaultValue : emotion;
            result.add(finalEmotion);
        }
        
        return result;
    }

    /**
     * 根据索引或值查找对应的 emotion
     * 优先使用索引，如果索引位置没有 emotion，则通过值在原始列表中的位置查找
     *
     * @param emotionList emotion 列表
     * @param matchList 用于匹配的值列表（value 或 code）
     * @param targetValue 目标值
     * @param index 当前索引
     * @return 找到的 emotion，如果找不到则返回 null
     */
    private String findEmotionByIndexOrValue(List<String> emotionList, List<String> matchList, 
                                             String targetValue, int index) {
        if (emotionList == null || matchList == null || targetValue == null) {
            return null;
        }
        
        // 优先使用索引位置
        if (index < emotionList.size()) {
            String emotion = emotionList.get(index);
            if (!Strings.isNullOrEmpty(emotion)) {
                return emotion;
            }
        }
        
        // 如果索引位置没有 emotion，则通过值在原始列表中的位置查找
        for (int i = 0; i < matchList.size() && i < emotionList.size(); i++) {
            String value = matchList.get(i);
            if (targetValue.equals(value)) {
                String emotion = emotionList.get(i);
                if (!Strings.isNullOrEmpty(emotion)) {
                    return emotion;
                }
            }
        }
        
        return null;
    }
}
