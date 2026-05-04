package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.UserIntentQueryReq;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerMajor;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 志愿过滤器链
 * 负责对志愿数据进行各种过滤处理
 */
@Slf4j
@Component
public class VolunteerFilterChain {

    /**
     * 构建查询条件
     */
    public UserIntentQueryReq buildQueryCondition(CreateSessionReq memberScoreDetail, UserProfileData userProfileData) {
        UserIntentQueryReq filterReq = new UserIntentQueryReq();

        // 专项计划
        filterReq.setHasZhuanXiangSpecial(memberScoreDetail.getSpecialPlan());

        // 色盲色弱过滤
        if (memberScoreDetail.getColorSistuation() != null
                && !memberScoreDetail.getColorSistuation().contains("normal")) {
            filterReq.setNeedCheckSemangSpecial(true);
        }
        // 少数民族
        if (memberScoreDetail.getEthnicity()!=null&&!"01".equals(memberScoreDetail.getEthnicity().getCode())) {
            filterReq.setHasMinority(true);
        }
        //中外合作
        if (memberScoreDetail.getAcceptForeignSchool() != null) {
            filterReq.setAcceptForeignSchool(memberScoreDetail.getAcceptForeignSchool());
        }

        // 学费区间过滤
        if (memberScoreDetail.getTuitionRange() != null) {
            if (memberScoreDetail.getTuitionRange().getMin() != null) {
                filterReq.setMinTuitionFeeM(memberScoreDetail.getTuitionRange().getMin());
            }
            if (memberScoreDetail.getTuitionRange().getMax() != null) {
                filterReq.setMaxTuitionFeeM(memberScoreDetail.getTuitionRange().getMax());
            }
        }

        // 用户选科
        List<String> subjects = memberScoreDetail.getSubjectList().stream()
                .map(subject -> subject.getName())
                .collect(java.util.stream.Collectors.toList());
        filterReq.setSubjects(subjects);

        // 概率过滤（预留接口）
//        filterReq.setMinSchoolEnrollRatio(20);
//        filterReq.setMinMajorEnrollRatio(20);

        // 用户会话中意愿
        if (userProfileData != null) {
            populateUserIntentFilters(filterReq, userProfileData);
        }

        return filterReq;
    }

    /**
     * 填充用户意愿过滤条件
     */
    private void populateUserIntentFilters(UserIntentQueryReq filterReq, UserProfileData userProfileData) {
        if (userProfileData == null) {
            return;
        }
        
        // 城市信息处理 - 正向和负向
        UserProfileData.CityInfo positiveCityInfo = userProfileData.getCity_info();
        UserProfileData.CityInfo negativeCityInfo = userProfileData.getNegative_city_info();

        //省份信息处理
        populateProvinceFilters(filterReq, positiveCityInfo, negativeCityInfo);
        //城市信息处理
        populateCityFilters(filterReq, positiveCityInfo, negativeCityInfo);

        // 学校信息处理（使用新结构，仅按code）
        populateSchoolFilters(filterReq, userProfileData.getCollege_info(), userProfileData.getNegative_college_info());

        // 专业信息处理
        populateMajorFilters(filterReq, userProfileData.getMajor_intent());

        // 负向专业信息处理
        populateNegativeMajorFilters(filterReq, userProfileData.getNegative_major_intent());
    }

    /**
     * 填充省份过滤条件(code)
     */
    private void populateProvinceFilters(UserIntentQueryReq filterReq, UserProfileData.CityInfo positiveCityInfo, UserProfileData.CityInfo negativeCityInfo) {
        // 正向省份
        if (positiveCityInfo != null && positiveCityInfo.getProvince_code() != null && !positiveCityInfo.getProvince_code().isEmpty()) {
            filterReq.setIncludeAreaIdList(positiveCityInfo.getProvince_code());
        } else {
            filterReq.setIncludeAreaIdList(Lists.newArrayList());
        }

        // 负向省份
        if (negativeCityInfo != null && negativeCityInfo.getProvince_code() != null) {
            filterReq.setExcludeProvinceIdList(negativeCityInfo.getProvince_code());
        } else {
            filterReq.setExcludeProvinceIdList(Lists.newArrayList());
        }
    }

    /**
     * 填充城市过滤条件
     */
    private void populateCityFilters(UserIntentQueryReq filterReq, UserProfileData.CityInfo positiveCityInfo, UserProfileData.CityInfo negativeCityInfo) {
        // 正向城市
        if (positiveCityInfo != null && positiveCityInfo.getCity_code() != null && !positiveCityInfo.getCity_code().isEmpty()) {
            filterReq.setIncludeCityIdList(positiveCityInfo.getCity_code());
        } else {
            filterReq.setIncludeCityIdList(Lists.newArrayList());
        }

        // 负向城市
        if (negativeCityInfo != null && negativeCityInfo.getCity_code() != null) {
            filterReq.setExcludeCityIdList(negativeCityInfo.getCity_code());
        } else {
            filterReq.setExcludeCityIdList(Lists.newArrayList());
        }
    }

    /**
     * 填充学校过滤条件
     */
    private void populateSchoolFilters(UserIntentQueryReq filterReq,
                                       UserProfileData.CollegeInfo positiveCollegeInfo,
                                       UserProfileData.CollegeInfo negativeCollegeInfo) {
        if (positiveCollegeInfo != null && positiveCollegeInfo.getValues_code() != null && !positiveCollegeInfo.getValues_code().isEmpty()) {
            filterReq.setIncludeSchoolIdList(positiveCollegeInfo.getValues_code());
        } else {
            filterReq.setIncludeSchoolIdList(Lists.newArrayList());
        }

        if (negativeCollegeInfo != null && negativeCollegeInfo.getValues_code() != null) {
            filterReq.setExcludeSchoolIdList(negativeCollegeInfo.getValues_code());
        } else {
            filterReq.setExcludeSchoolIdList(Lists.newArrayList());
        }
    }

    /**
     * 填充专业过滤条件
     */
    private void populateMajorFilters(UserIntentQueryReq filterReq, UserProfileData.MajorIntent majorIntent) {
        if (majorIntent != null) {
            // 正向专业 - 二级专业
            if (majorIntent.getLevel2_code() != null && !majorIntent.getLevel2_code().isEmpty()) {
                filterReq.setIncludeMajorSecondLevelIdList(majorIntent.getLevel2_code());
            } else {
                filterReq.setIncludeMajorSecondLevelIdList(Lists.newArrayList());
            }

            // 正向专业 - 三级专业
            if (majorIntent.getLevel3_code() != null && !majorIntent.getLevel3_code().isEmpty()) {
                filterReq.setIncludeMajorIdList(majorIntent.getLevel3_code());
            } else {
                filterReq.setIncludeMajorIdList(Lists.newArrayList());
            }
        } else {
            filterReq.setIncludeMajorSecondLevelIdList(Lists.newArrayList());
            filterReq.setIncludeMajorIdList(Lists.newArrayList());
        }
    }

    /**
     * 填充负向专业过滤条件
     */
    private void populateNegativeMajorFilters(UserIntentQueryReq filterReq, UserProfileData.MajorIntent negativeMajorIntent) {
        if (negativeMajorIntent != null) {
            // 负向专业 - 二级专业
            if (negativeMajorIntent.getLevel2_code() != null) {
                filterReq.setExcludeMajorSecondLevelIdList(negativeMajorIntent.getLevel2_code());
            } else {
                filterReq.setExcludeMajorSecondLevelIdList(Lists.newArrayList());
            }

            // 负向专业 - 三级专业
            if (negativeMajorIntent.getLevel3_code() != null) {
                filterReq.setExcludeMajorIdList(negativeMajorIntent.getLevel3_code());
            } else {
                filterReq.setExcludeMajorIdList(Lists.newArrayList());
            }
        } else {
            filterReq.setExcludeMajorSecondLevelIdList(Lists.newArrayList());
            filterReq.setExcludeMajorIdList(Lists.newArrayList());
        }
    }

    /**
     * 过滤志愿数据
     * 基于筛选条件从全量志愿数据中过滤出符合条件的志愿
     *
     * @param filterReq         筛选条件
     * @param volunteerFullData 全量志愿数据
     * @return 过滤后的志愿数据
     */
    public List<VolunteerSchoolGroup> filterVolunteerData(UserIntentQueryReq filterReq, List<VolunteerSchoolGroup> volunteerFullData) {
        log.info("开始过滤志愿数据，筛选条件: {}", filterReq);

        if (volunteerFullData == null || volunteerFullData.isEmpty()) {
            log.warn("志愿数据为空，直接返回空列表");
            return new ArrayList<>();
        }

        List<VolunteerSchoolGroup> filteredData = new ArrayList<>();
        
        // 统计过滤原因
        int totalSchoolCount = volunteerFullData.size();
        int totalMajorCount = volunteerFullData.stream().mapToInt(sg -> sg.getMajorList() != null ? sg.getMajorList().size() : 0).sum();
        int filteredBySchoolLevel = 0; // 学校级别被过滤的数量
        int filteredByMajorLevel = 0; // 专业级别被过滤的数量

        for (VolunteerSchoolGroup schoolGroup : volunteerFullData) {
            int originalMajorCount = schoolGroup.getMajorList() != null ? schoolGroup.getMajorList().size() : 0;
            
            // 过滤专业列表
            List<VolunteerMajor> filteredMajors = filterMajors(filterReq, schoolGroup.getMajorList(), schoolGroup);

            // 如果过滤后没有专业了，跳过这个学校组
            if (filteredMajors.isEmpty()) {
                if (originalMajorCount > 0) {
                    filteredBySchoolLevel++;
                    log.debug("学校 {} 的所有专业都被过滤掉，跳过 (原专业数: {})", schoolGroup.getSchoolName(), originalMajorCount);
                }
                continue;
            }

            // 统计专业级别的过滤
            filteredByMajorLevel += (originalMajorCount - filteredMajors.size());

            // 直接使用原始对象，因为原始数据的majorList从未被修改
            schoolGroup.setMajorList(filteredMajors);
            filteredData.add(schoolGroup);
        }

        log.info("志愿数据过滤完成，过滤前学校数量: {}, 过滤后学校数量: {}, 过滤前专业总数: {}, 学校级别过滤: {}个学校, 专业级别过滤: {}个专业",
                totalSchoolCount, filteredData.size(), totalMajorCount, filteredBySchoolLevel, filteredByMajorLevel);
        
        if (filteredData.isEmpty() && totalSchoolCount > 0) {
            log.warn("所有志愿数据都被过滤掉！可能的原因：1.中外合作过滤(acceptForeignSchool=false) 2.选科不匹配 3.学费超出范围 4.其他条件限制");
        }

        return filteredData;
    }

    /**
     * 过滤专业列表
     */
    public List<VolunteerMajor> filterMajors(UserIntentQueryReq filterReq, List<VolunteerMajor> majorList, VolunteerSchoolGroup schoolGroup) {
        if (majorList == null || majorList.isEmpty()) {
            return new ArrayList<>();
        }

        // 如果schoolGroup里的schoolName里有少数民族、或者专项计划也要进行过滤。此时给其majorList为空即可，最终会移除。
        if (schoolGroup != null) {
            // 1. 色盲色弱过滤
            if (isColorBlindnessFiltered(filterReq, schoolGroup.getSchoolName())) {
                log.debug("学校 {} 因色盲色弱限制被过滤", schoolGroup.getSchoolName());
                return new ArrayList<>();
            }

            // 2. 专项计划过滤
            if (isSpecialPlanFiltered(filterReq, schoolGroup.getSchoolName())) {
                log.debug("学校 {} 因专项计划限制被过滤", schoolGroup.getSchoolName());
                return new ArrayList<>();
            }

            // 3. 少数民族过滤：如果用户不是少数民族，可院校里名字里包含少数民族，则专业过滤掉。
            if (isMinorityFiltered(filterReq, schoolGroup.getSchoolName())) {
                log.debug("学校 {} 因少数民族限制被过滤", schoolGroup.getSchoolName());
                return new ArrayList<>();
            }
            // 4. 中外合作过滤：如果用户接受中外合作，可院校里名字里包含中外合作，则保留，不接受，则去掉。
            if (isForeignSchoolFiltered(filterReq, schoolGroup.getSchoolName())) {
                log.debug("学校 {} 因不接受中外合作限制被过滤 (acceptForeignSchool={})", 
                    schoolGroup.getSchoolName(), filterReq.getAcceptForeignSchool());
                return new ArrayList<>();
            }
        }

        List<VolunteerMajor> filteredMajors = new ArrayList<>();
        
        // 统计各过滤条件的过滤数量
        int colorBlindnessCount = 0;
        int specialPlanCount = 0;
        int minorityCount = 0;
        int foreignSchoolCount = 0;
        int tuitionCount = 0;
        int enrollRatioCount = 0;
        int subjectCount = 0;

        for (VolunteerMajor major : majorList) {
            // 1. 色盲色弱过滤
            if (isColorBlindnessFiltered(filterReq, major.getMajorName())) {
                colorBlindnessCount++;
                log.debug("专业 {} 因色盲色弱限制被过滤", major.getMajorName());
                continue;
            }

            // 2. 专项计划过滤
            if (isSpecialPlanFiltered(filterReq, major.getMajorName())) {
                specialPlanCount++;
                log.debug("专业 {} 因专项计划限制被过滤", major.getMajorName());
                continue;
            }

            // 3. 少数民族过滤：如果用户不是少数民族，可专业里名字里包含少数民族，则专业过滤掉。
            if (isMinorityFiltered(filterReq, major.getMajorName())) {
                minorityCount++;
                log.debug("专业 {} 因少数民族限制被过滤", major.getMajorName());
                continue;
            }
            // 4. 中外合作过滤：如果用户接受中外合作，可院校里名字里包含中外合作，则保留，不接受，则去掉。
            if (isForeignSchoolFiltered(filterReq, major.getMajorName())) {
                foreignSchoolCount++;
                log.debug("专业 {} 因不接受中外合作限制被过滤 (acceptForeignSchool={})", 
                    major.getMajorName(), filterReq.getAcceptForeignSchool());
                continue;
            }

            // 5. 学费区间过滤
            if (isTuitionFiltered(filterReq, major)) {
                tuitionCount++;
                log.debug("专业 {} 因学费区间限制被过滤, planMoney={}, 范围=[{}, {}]", 
                    major.getMajorName(), major.getPlanMoney(), 
                    filterReq.getMinTuitionFeeM(), filterReq.getMaxTuitionFeeM());
                continue;
            }

            // 6. 录取概率过滤
            if (isEnrollRatioFiltered(filterReq, major)) {
                enrollRatioCount++;
                log.debug("专业 {} 因录取概率限制被过滤, ratio={}", major.getMajorName(), major.getMajorEnrollRatio());
                continue;
            }

            // 7. 选科过滤
            if (isSubjectFiltered(filterReq, major)) {
                subjectCount++;
                log.debug("专业 {} 因选科限制被过滤, selectInfo={}, userSubjects={}", 
                    major.getMajorName(), major.getSelectInfo(), filterReq.getSubjects());
                continue;
            }

//            // 6. 地域过滤
//            if (isLocationFiltered(filterReq, schoolGroup)) {
//                log.debug("学校 {} 因地域限制被过滤", schoolGroup.getSchoolName());
//                continue;
//            }
//
//            // 7. 院校过滤
//            if (isSchoolFiltered(filterReq, schoolGroup)) {
//                log.debug("学校 {} 因院校限制被过滤", schoolGroup.getSchoolName());
//                continue;
//            }
//
//            // 8. 专业过滤
//            if (isMajorFiltered(filterReq, major)) {
//                log.debug("专业 {} 因专业限制被过滤", major.getMajorName());
//                continue;
//            }

            filteredMajors.add(major);
        }
        
        // 如果所有专业都被过滤，记录详细统计信息
        if (filteredMajors.isEmpty() && majorList.size() > 0 && schoolGroup != null) {
            log.warn("学校 {} 的所有 {} 个专业都被过滤，过滤统计: 色盲色弱={}, 专项计划={}, 少数民族={}, 中外合作={}, 学费={}, 录取概率={}, 选科={}", 
                schoolGroup.getSchoolName(), majorList.size(),
                colorBlindnessCount, specialPlanCount, minorityCount, foreignSchoolCount,
                tuitionCount, enrollRatioCount, subjectCount);
        }

        return filteredMajors;
    }

    /**
     * 色盲色弱过滤
     */
    private boolean isColorBlindnessFiltered(UserIntentQueryReq filterReq, String name) {
        if (filterReq.getNeedCheckSemangSpecial() == null || !filterReq.getNeedCheckSemangSpecial()) {
            return false;
        }

        if (name == null) {
            return false;
        }

        // 检查专业名称是否包含色盲或色弱关键词
        return name.contains("色盲") || name.contains("色弱");
    }

    /**
     * 专项计划过滤
     */
    private boolean isSpecialPlanFiltered(UserIntentQueryReq filterReq, String name) {
        if (filterReq.getHasZhuanXiangSpecial() == null || filterReq.getHasZhuanXiangSpecial()) {
            return false;
        }

        if (name == null) {
            return false;
        }

        // 检查专业名称是否包含专项计划关键词
        return name.contains("专项计划")||name.contains("国家专项")||name.contains("地方专项");
    }

    /**
     * 录取概率过滤
     */
    private boolean isEnrollRatioFiltered(UserIntentQueryReq filterReq, VolunteerMajor major) {
        // 检查专业录取概率
        if (major.getMajorEnrollRatio() != null) {
            double majorRatio = major.getMajorEnrollRatio();

            if (filterReq.getMinMajorEnrollRatio() != null && majorRatio < filterReq.getMinMajorEnrollRatio()) {
                return true;
            }

            if (filterReq.getMaxMajorEnrollRatio() != null && majorRatio > filterReq.getMaxMajorEnrollRatio()) {
                return true;
            }
        }

        return false;
    }

    /**
     * 学费区间过滤
     */
    private boolean isTuitionFiltered(UserIntentQueryReq filterReq, VolunteerMajor major) {
        Integer minTuition = filterReq.getMinTuitionFeeM();
        Integer maxTuition = filterReq.getMaxTuitionFeeM();

        // 未配置学费区间，则不做过滤
        if (minTuition == null && maxTuition == null) {
            return false;
        }

        String planMoneyStr = major.getPlanMoney();
        if (planMoneyStr == null || planMoneyStr.trim().isEmpty()) {
            // 学费缺失时，为避免误伤，先不过滤
            return false;
        }

        // 提取其中的数字部分，例如 "5000元/年" -> 5000
        String digits = planMoneyStr.replaceAll("[^0-9]", "");
        if (digits.isEmpty()) {
            return false;
        }

        Integer tuition;
        try {
            tuition = Integer.parseInt(digits);
        } catch (NumberFormatException e) {
            // 解析失败则不进行学费过滤
            return false;
        }

        if (minTuition != null && tuition < minTuition) {
            return true;
        }

        if (maxTuition != null && tuition > maxTuition) {
            return true;
        }

        return false;
    }

    /**
     * 少数民族过滤
     * 如果用户不是少数民族，且专业名称包含少数民族相关关键词，则过滤掉该专业
     */
    private boolean isMinorityFiltered(UserIntentQueryReq filterReq, String name) {
        // 如果用户是少数民族，不过滤
        if (filterReq.getHasMinority() != null && filterReq.getHasMinority()) {
            return false;
        }

        if (name == null) {
            return false;
        }

        // 检查专业名称是否包含少数民族相关关键词
        return  name.contains("民族班");
    }

    /**
     * 是否接受中外合作过滤
     如果用户接受中外合作，可院校里名字里包含中外合作，则保留，不接受，则去掉。
     */
    private boolean isForeignSchoolFiltered(UserIntentQueryReq filterReq, String name) {
        // 如果用户接受中外合作，不过滤
        if (filterReq.getAcceptForeignSchool() != null && filterReq.getAcceptForeignSchool()) {
            return false;
        }

        if (name == null) {
            return false;
        }

        // 检查专业名称是否包含中外合作相关关键词
        return name.contains("中外合作");
    }

    /**
     * 选科过滤
     * 根据专业选科要求和用户选科列表进行匹配
     */
    private boolean isSubjectFiltered(UserIntentQueryReq filterReq, VolunteerMajor major) {
        String selectInfo = major.getSelectInfo();
        List<String> userSubjects = filterReq.getSubjects();

        // 如果专业没有选科要求，不过滤
        if (selectInfo == null || selectInfo.trim().isEmpty()) {
            return false;
        }

        // 如果用户没有选科信息，不过滤（可能是数据不完整）
        if (userSubjects == null || userSubjects.isEmpty()) {
            return false;
        }

        // 解析专业选科要求
        List<String> requiredSubjects = parseSelectInfo(selectInfo);
        if (requiredSubjects.isEmpty()) {
            return false;
        }

        // 检查用户选科是否满足专业要求
        return !userSubjects.containsAll(requiredSubjects);
    }

    /**
     * 解析专业选科要求
     * 支持格式：物和化、物、化、历和政等
     */
    private List<String> parseSelectInfo(String selectInfo) {
        List<String> requiredSubjects = new ArrayList<>();

        if (selectInfo == null || selectInfo.trim().isEmpty()) {
            return requiredSubjects;
        }

        String info = selectInfo.trim();

        // 处理"和"连接的多个学科
        if (info.contains("和")) {
            String[] subjects = info.split("和");
            for (String subject : subjects) {
                String fullName = convertSubjectAbbreviation(subject.trim());
                if (fullName != null && !fullName.isEmpty()) {
                    requiredSubjects.add(fullName);
                }
            }
        } else {
            // 单个学科
            String fullName = convertSubjectAbbreviation(info);
            if (fullName != null && !fullName.isEmpty()) {
                requiredSubjects.add(fullName);
            }
        }

        return requiredSubjects;
    }

    /**
     * 转换学科缩写为全称
     */
    private String convertSubjectAbbreviation(String abbr) {
        if (abbr == null) {
            return null;
        }

        switch (abbr.trim()) {
            case "物":
                return "物理";
            case "化":
                return "化学";
            case "生":
                return "生物";
            case "政":
                return "政治";
            case "史":
                return "历史";
            case "地":
                return "地理";
            default:
                // 如果已经是全称，直接返回
                if (abbr.contains("物理") || abbr.contains("化学") || abbr.contains("生物") ||
                        abbr.contains("政治") || abbr.contains("历史") || abbr.contains("地理")) {
                    return abbr;
                }
                return null;
        }
    }

    /**
     * 地域过滤
     */
    private boolean isLocationFiltered(UserIntentQueryReq filterReq, VolunteerSchoolGroup schoolGroup) {
        // 检查省份排除列表
        if (filterReq.getExcludeProvinceIdList() != null && !filterReq.getExcludeProvinceIdList().isEmpty()) {
            if (schoolGroup.getProvinceId() != null && filterReq.getExcludeProvinceIdList().contains(schoolGroup.getProvinceId())) {
                return true;
            }
        }

        // 检查城市排除列表
        if (filterReq.getExcludeCityIdList() != null && !filterReq.getExcludeCityIdList().isEmpty()) {
            if (schoolGroup.getCityId() != null && filterReq.getExcludeCityIdList().contains(schoolGroup.getCityId())) {
                return true;
            }
        }

        // 检查省份包含列表
        if (filterReq.getIncludeAreaIdList() != null && !filterReq.getIncludeAreaIdList().isEmpty()) {
            if (schoolGroup.getProvinceId() == null || !filterReq.getIncludeAreaIdList().contains(schoolGroup.getProvinceId())) {
                return true;
            }
        }

        // 检查城市包含列表
        if (filterReq.getIncludeCityIdList() != null && !filterReq.getIncludeCityIdList().isEmpty()) {
            if (schoolGroup.getCityId() == null || !filterReq.getIncludeCityIdList().contains(schoolGroup.getCityId())) {
                return true;
            }
        }

        return false;
    }

    /**
     * 院校过滤
     */
    private boolean isSchoolFiltered(UserIntentQueryReq filterReq, VolunteerSchoolGroup schoolGroup) {
        // 检查院校排除列表
        if (filterReq.getExcludeSchoolIdList() != null && !filterReq.getExcludeSchoolIdList().isEmpty()) {
            if (schoolGroup.getSchoolId() != null && filterReq.getExcludeSchoolIdList().contains(schoolGroup.getSchoolId())) {
                return true;
            }
        }

        // 检查院校包含列表
        if (filterReq.getIncludeSchoolIdList() != null && !filterReq.getIncludeSchoolIdList().isEmpty()) {
            if (schoolGroup.getSchoolId() == null || !filterReq.getIncludeSchoolIdList().contains(schoolGroup.getSchoolId())) {
                return true;
            }
        }

        return false;
    }

    /**
     * 专业过滤
     */
    private boolean isMajorFiltered(UserIntentQueryReq filterReq, VolunteerMajor major) {
        // 检查专业ID是否在排除列表中
        if (filterReq.getExcludeMajorIdList() != null && !filterReq.getExcludeMajorIdList().isEmpty()) {
            if (major.getMajorId() != null && filterReq.getExcludeMajorIdList().contains(major.getMajorId())) {
                return true;
            }
        }

        // 检查专业二级分类是否在排除列表中
        if (filterReq.getExcludeMajorSecondLevelIdList() != null && !filterReq.getExcludeMajorSecondLevelIdList().isEmpty()) {
            if (major.getSubCategoryId() != null && filterReq.getExcludeMajorSecondLevelIdList().contains(major.getSubCategoryId())) {
                return true;
            }
        }

        // 如果设置了包含列表，检查是否在包含列表中
        if (filterReq.getIncludeMajorIdList() != null && !filterReq.getIncludeMajorIdList().isEmpty()) {
            if (major.getMajorId() == null || !filterReq.getIncludeMajorIdList().contains(major.getMajorId())) {
                return true;
            }
        }

        if (filterReq.getIncludeMajorSecondLevelIdList() != null && !filterReq.getIncludeMajorSecondLevelIdList().isEmpty()) {
            if (major.getSubCategoryId() == null || !filterReq.getIncludeMajorSecondLevelIdList().contains(major.getSubCategoryId())) {
                return true;
            }
        }

        return false;
    }

}
