package com.ytell.zhiyuan.service.biz;

import cn.hutool.core.util.NumberUtil;
import com.google.common.base.Splitter;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.manager.SchoolProfileManager;
import com.ytell.zhiyuan.model.dto.SchoolProfileDto;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.SchoolRecommendResponse;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerMajor;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.*;
import java.util.stream.Collectors;

/**
 * 负责志愿数据推荐的数据构造
 */
@Slf4j
@Component
public class VolunteerRecommendBuilder {

    @Autowired
    private SchoolProfileManager schoolProfileManager;

    @Autowired
    private SchoolManager schoolManager;

    @Autowired
    private VolunteerUtils volunteerUtils;

    /**
     * 学校聚合信息内部类（专业+院校模式）
     */
    private static class SchoolMajorAggregationInfo {
        String schoolId;
        String schoolName;
        List<String> majors;
    }

    /**
     * 学校聚合信息内部类（专业组模式）
     */
    private static class SchoolAggregationInfo {
        String schoolId;
        String schoolName;
        List<MajorGroupInfo> majorGroups;
    }

    /**
     * 专业组信息内部类
     */
    private static class MajorGroupInfo {
        String groupName;
        List<String> majors;
    }

    /**
     * 专业+院校模式下从冲稳保列表中截取学校信息
     * 按照冲->稳->保的顺序截取5个学校，每个学校最多取4个专业
     *
     * @param allVolunteerSchools 志愿推荐响应数据
     * @return 学校信息列表
     */
    public List<SchoolRecommendResponse.SchoolInfo> extractSchoolsForMajorSchoolMode(List<VolunteerRecommendListResponse.VolunteerSchool> allVolunteerSchools) {
        List<SchoolRecommendResponse.SchoolInfo> schoolInfoList = new ArrayList<>();
        int maxSchoolCount = 5; // 最多截取5个学校
        int maxMajorPerSchool = 4; // 每个学校最多4个专业

        // 2. 按照schoolId聚合专业，使用LinkedHashMap保持插入顺序
        Map<String, SchoolMajorAggregationInfo> schoolAggregationMap = new LinkedHashMap<>();

        for (VolunteerRecommendListResponse.VolunteerSchool volunteerSchool : allVolunteerSchools) {
            String schoolId = volunteerSchool.getSchoolId();
            if (schoolId == null || schoolId.trim().isEmpty()) {
                continue;
            }

            // 获取或创建学校聚合信息
            SchoolMajorAggregationInfo aggregationInfo = schoolAggregationMap.get(schoolId);
            if (aggregationInfo == null) {
                aggregationInfo = new SchoolMajorAggregationInfo();
                aggregationInfo.schoolId = schoolId;
                aggregationInfo.schoolName = volunteerSchool.getSchool_name();
                aggregationInfo.majors = new ArrayList<>();
                schoolAggregationMap.put(schoolId, aggregationInfo);
            }

            // 提取专业信息并添加到聚合列表中
            if (volunteerSchool.getMajors() != null) {
                for (VolunteerRecommendListResponse.VolunteerMajor major : volunteerSchool.getMajors()) {
                    if (major.getMajor_name() != null && !major.getMajor_name().trim().isEmpty()) {
                        // 清理专业名称中的括号内容
                        String cleanedMajorName = volunteerUtils.removeBracketsFromMajorName(major.getMajor_name());
                        aggregationInfo.majors.add(cleanedMajorName);
                    }
                }
            }
        }

        log.info("专业+院校模式按schoolId聚合完成，学校数量: {}", schoolAggregationMap.size());

        // 3. 生成推荐结果，最多取5个学校
        int schoolCount = 0;
        for (SchoolMajorAggregationInfo aggregationInfo : schoolAggregationMap.values()) {
            if (schoolCount >= maxSchoolCount) {
                break;
            }

            SchoolRecommendResponse.SchoolInfo schoolInfo = new SchoolRecommendResponse.SchoolInfo();
            schoolInfo.setSchoolId(aggregationInfo.schoolId);
            schoolInfo.setSchoolName(aggregationInfo.schoolName);

            // 提取专业信息，最多取4个专业，保持相对顺序
            List<String> majorList = new ArrayList<>();
            int majorCount = Math.min(aggregationInfo.majors.size(), maxMajorPerSchool);
            for (int i = 0; i < majorCount; i++) {
                majorList.add(aggregationInfo.majors.get(i));
            }

            schoolInfo.setMajorList(majorList);
            schoolInfoList.add(schoolInfo);
            schoolCount++;
        }

        log.info("专业+院校模式截取完成，共{}所学校", schoolInfoList.size());
        return schoolInfoList;
    }

    /**
     * 专业组模式下从冲稳保列表中截取学校信息
     * 1. 按照schoolId聚合，保持同一schoolId下专业组的相对顺序
     * 2. 生成推荐结果，每个专业组的字符串描述格式为：专业组名称(专业1,专业2...)
     * 3. 最多截取5个学校，每个学校最多4个专业组，每个专业组最多包含4个专业
     *
     * @param allVolunteerSchools 志愿推荐响应数据
     * @return 学校信息列表
     */
    public List<SchoolRecommendResponse.SchoolInfo> extractSchoolsForMajorGroupMode(List<VolunteerRecommendListResponse.VolunteerSchool> allVolunteerSchools) {
        List<SchoolRecommendResponse.SchoolInfo> schoolInfoList = new ArrayList<>();
        int maxSchoolCount = 5; // 最多截取5个学校
        int maxMajorGroupPerSchool = 4; // 每个学校最多4个专业组
        int maxMajorPerGroup = 4; // 每个专业组最多4个专业


        log.info("专业组模式合并列表完成，总数量: {}", allVolunteerSchools.size());

        // 2. 按照schoolId聚合，使用LinkedHashMap保持插入顺序
        Map<String, SchoolAggregationInfo> schoolAggregationMap = new LinkedHashMap<>();

        for (VolunteerRecommendListResponse.VolunteerSchool volunteerSchool : allVolunteerSchools) {
            String schoolId = volunteerSchool.getSchoolId();
            if (schoolId == null || schoolId.trim().isEmpty()) {
                continue;
            }

            // 获取或创建学校聚合信息
            SchoolAggregationInfo aggregationInfo = schoolAggregationMap.get(schoolId);
            if (aggregationInfo == null) {
                aggregationInfo = new SchoolAggregationInfo();
                aggregationInfo.schoolId = schoolId;
                // 在专业组模式下，schoolName来自SchoolManager而不是VolunteerSchool.school_name
                SchoolVO schoolVO = schoolManager.getSchoolById(schoolId);
                aggregationInfo.schoolName = (schoolVO != null) ? schoolVO.getSchoolName() : schoolId;
                aggregationInfo.majorGroups = new ArrayList<>();
                schoolAggregationMap.put(schoolId, aggregationInfo);
            }

            // 添加专业组信息（VolunteerSchool.school_name是专业组名称）
            MajorGroupInfo majorGroupInfo = new MajorGroupInfo();
            majorGroupInfo.groupName = volunteerSchool.getSchool_name(); // 专业组名称
            majorGroupInfo.majors = new ArrayList<>();

            // 提取专业信息
            if (volunteerSchool.getMajors() != null) {
                int majorCount = Math.min(volunteerSchool.getMajors().size(), maxMajorPerGroup);
                for (int i = 0; i < majorCount; i++) {
                    VolunteerRecommendListResponse.VolunteerMajor major = volunteerSchool.getMajors().get(i);
                    if (major.getMajor_name() != null && !major.getMajor_name().trim().isEmpty()) {
                        // 清理专业名称中的括号内容
                        String cleanedMajorName = volunteerUtils.removeBracketsFromMajorName(major.getMajor_name());
                        majorGroupInfo.majors.add(cleanedMajorName);
                    }
                }
            }

            aggregationInfo.majorGroups.add(majorGroupInfo);
        }

        log.info("专业组模式按schoolId聚合完成，学校数量: {}", schoolAggregationMap.size());

        // 3. 生成推荐结果，最多取5个学校
        int schoolCount = 0;
        for (SchoolAggregationInfo aggregationInfo : schoolAggregationMap.values()) {
            if (schoolCount >= maxSchoolCount) {
                break;
            }

            SchoolRecommendResponse.SchoolInfo schoolInfo = new SchoolRecommendResponse.SchoolInfo();
            schoolInfo.setSchoolId(aggregationInfo.schoolId);
            schoolInfo.setSchoolName(aggregationInfo.schoolName);

            // 构建专业组描述列表，最多取4个专业组
            List<String> majorGroupDescriptions = new ArrayList<>();
            int groupCount = Math.min(aggregationInfo.majorGroups.size(), maxMajorGroupPerSchool);
            for (int i = 0; i < groupCount; i++) {
                MajorGroupInfo majorGroupInfo = aggregationInfo.majorGroups.get(i);
                String description = buildMajorGroupDescription(majorGroupInfo);
                majorGroupDescriptions.add(description);
            }

            schoolInfo.setMajorList(majorGroupDescriptions);
            schoolInfoList.add(schoolInfo);
            schoolCount++;
        }

        log.info("专业组模式截取完成，共{}所学校", schoolInfoList.size());
        return schoolInfoList;
    }

    /**
     * 构建专业组描述字符串
     * 格式：专业组名称(专业1,专业2,专业3,专业4)
     *
     * @param majorGroupInfo 专业组信息
     * @return 专业组描述字符串
     */
    private String buildMajorGroupDescription(MajorGroupInfo majorGroupInfo) {
        StringBuilder description = new StringBuilder();
        description.append(majorGroupInfo.groupName);

        if (majorGroupInfo.majors != null && !majorGroupInfo.majors.isEmpty()) {
            description.append("[");
            description.append(String.join(",", majorGroupInfo.majors));
            description.append("]");
        }

        return description.toString();
    }

    /**
     * 从志愿数据详情构建志愿学校信息
     */
    public VolunteerRecommendListResponse.VolunteerSchool buildVolunteerSchoolFromDetail(VolunteerSchoolGroup detail, UserProfileData userFinalProfileData) {

        //构建返回
        VolunteerRecommendListResponse.VolunteerSchool school = new VolunteerRecommendListResponse.VolunteerSchool();
        // 从SchoolProfileManager获取学校画像信息
        SchoolProfileDto schoolProfile = schoolProfileManager.getSchoolProfileById(detail.getSchoolId());
        //1.院校基本信息
        school.setSchoolId(detail.getSchoolId());
        school.setSchool_name(detail.getSchoolName());
        school.setSchoolUnitCode(detail.getSchoolUnitCode());
        school.setPlanSchoolDataId(detail.getPlanSchoolDataId());
        school.setProvince_name(detail.getProvinceName());
        school.setCity_name(detail.getCityName());
        // 群组本来就带着 ID（`VolunteerDataTransformService:70-75` ✓），以前只写了名字 ✗
        // → 从这里往下（候选池 / 约束 / 匹配）就只剩名字 ✓。补上，别在源头丢 ✓。
        school.setProvince_id(detail.getProvinceId());
        school.setCity_id(detail.getCityId());
        school.setSchool_batch(schoolProfile.getBatch());
        school.setSchool_level(schoolProfile.getLevel());
        school.setSchool_nature(schoolProfile.getNature());
        school.setSchool_category(schoolProfile.getCategory());
        //2.院校荣誉
        //院校排名
        school.setSchool_rank(detail.getSchoolRank());
        //院校保研率
        if (schoolProfile.getPostgraduateRecommendRatio() != null && !schoolProfile.getPostgraduateRecommendRatio().trim().isEmpty()) {
            String ratio = schoolProfile.getPostgraduateRecommendRatio();
            ratio = ratio.replace("%", "");
            if (NumberUtil.isNumber(ratio)) {
                Double ratioNumber = Double.parseDouble(ratio);
                if (ratioNumber != null && ratioNumber > 0) {
                    school.setBaoyan_ratio(ratioNumber);
                }
            }
        }
        //院校升学率
        if (schoolProfile.getUpgradeRatio() != null && !schoolProfile.getUpgradeRatio().trim().isEmpty()) {
            String ratio = schoolProfile.getUpgradeRatio();
            ratio = ratio.replace("%", "");
            if (NumberUtil.isNumber(ratio)) {
                Double ratioNumber = Double.parseDouble(ratio);
                if (ratioNumber != null && ratioNumber > 0) {
                    school.setUpgrade_ratio(ratioNumber);
                }
            }
        }

        // 院校硕士点数量
        if (schoolProfile.getFirstLevelMasterStation() != null && !schoolProfile.getFirstLevelMasterStation().trim().isEmpty()) {
            String countStr= schoolProfile.getFirstLevelMasterStation().trim();
            if (NumberUtil.isNumber(countStr)) {
                Integer count = Integer.parseInt(countStr);
                if (count != null ) {
                    school.setMaster_count(count);
                }
            }
        }

        // 院校博士点数量
        if (schoolProfile.getFirstLevelDoctorStation() != null && !schoolProfile.getFirstLevelDoctorStation().trim().isEmpty()) {
           String countStr= schoolProfile.getFirstLevelDoctorStation().trim();
            if (NumberUtil.isNumber(countStr)) {
                Integer count = Integer.parseInt(countStr);
                if (count != null ) {
                    school.setDoctor_count(count);
                }
            }
        }
         //3.院校录取情况
        //录取率
        school.setEnroll_ratio(detail.getSchoolEnrollRatioStr());
        //志愿等级
        school.setLevel(detail.getSchoolVolunteerLevel());
        // 构建学校历史分数列表 - 从HistoryRecordDTO转换为HistoryScore
        if (detail.getHistoryRecords() != null && !detail.getHistoryRecords().isEmpty()) {
            List<VolunteerRecommendListResponse.HistoryScore> historyScoreList = volunteerUtils.buildHistoryScoreList(detail.getHistoryRecords());
            school.setHistory_score_list(historyScoreList);
        }
        //4.院校各种展示标签
        //构建学校标签
        school.setPopTagList(buildSchoolPopTagList(school));
        school.setBasicTagList(buildSchoolBasicTagList(school));
        school.setRankTagList(buildSchoolRankTagList(detail, schoolProfile, userFinalProfileData));

        //构建算法标签
        // 院校评估指标作为算法标签
        school.setAlgTagMap(buildSchoolAlgTagMap(detail, schoolProfile));


        // 5.构建院校下专业列表
        List<VolunteerRecommendListResponse.VolunteerMajor> majors = new ArrayList<>();
        if (detail.getMajorList() != null) {
            majors = detail.getMajorList().stream()
                    .map(one -> this.buildVolunteerMajorFromDetail(one, userFinalProfileData))
                    .collect(Collectors.toList());
        }
        school.setMajors(majors);

        return school;
    }

    /**
     * 从志愿数据详情构建志愿专业信息
     */
    private VolunteerRecommendListResponse.VolunteerMajor buildVolunteerMajorFromDetail(VolunteerMajor majorDetail, UserProfileData userFinalProfileData) {
        VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
        major.setPlanMajorDataId(majorDetail.getPlanMajorDataId());
        major.setMajor_name(majorDetail.getMajorName());
        major.setEnroll_ratio(majorDetail.getMajorEnrollRatioStr());
        major.setLevel(majorDetail.getMajorVolunteerLevel());
        major.setPlanNum(majorDetail.getPlanNum());
        major.setMajorUnitCode(majorDetail.getMajorUnitCode());
        major.setPlanMoney(majorDetail.getPlanMoney());
        major.setDuration(majorDetail.getDuration());
        major.setMajorId(majorDetail.getMajorId());
        major.setCategoryId(majorDetail.getCategoryId());
        major.setSubCategoryId(majorDetail.getSubCategoryId());

        // 构建必选科目
        major.setMust_subject(Lists.newArrayList(majorDetail.getSelectInfo()));

        // 构建历史分数列表 - 从HistoryRecordDTO转换为HistoryScore
        if (majorDetail.getHistoryRecords() != null && !majorDetail.getHistoryRecords().isEmpty()) {
            List<VolunteerRecommendListResponse.HistoryScore> historyScoreList = volunteerUtils.buildHistoryScoreList(majorDetail.getHistoryRecords());
            major.setHistory_score_list(historyScoreList);
        }
        //构建Major标签
        major.setPlanTagList(buildMajorPlanTagList(majorDetail));
        major.setRankTagList(buildMajorRankTagList(majorDetail, userFinalProfileData));

        //构建算法标签
        // 专业评估指标作为算法标签
        major.setAlgTagMap(buildMajorAlgTagMap(majorDetail));

        return major;
    }

    private List<String> buildMajorPlanTagList(VolunteerMajor majorDetail) {
        List<String> tags = Lists.newArrayList();
        if (majorDetail.getPlanNum() != null) {
            tags.add("计划数：" + majorDetail.getPlanNum());
        }
        if (majorDetail.getDuration() != null) {
            tags.add("学制：" + majorDetail.getDuration() + "年");
        }
        if (majorDetail.getPlanMoney() != null) {
            tags.add("学费：" + majorDetail.getPlanMoney() + "/年");
        }
        return tags;
    }

    private List<String> buildMajorRankTagList(VolunteerMajor majorDetail, UserProfileData userFinalProfileData) {
        List<String> tags = Lists.newArrayList();
        //专业热度、硕士点、博士点、学科评估
        Double hot = majorDetail.getHot_index();
        String degree = majorDetail.getDegree();
        String majorLevel = majorDetail.getMajor_level();
        if (hot != null && hot > 0) {
            tags.add("专业热度" + hot.intValue());
        }
        if (degree != null) {
            if ("doctor".equals(degree)) {
                tags.add("硕士点");
                tags.add("博士点");
            }
            if ("master".equals(degree)) {
                tags.add("硕士点");
            }
        }
        if (majorLevel != null && !"null".equals(majorLevel)) {
            tags.add("学科评估" + majorLevel);
        }
        //判断意向专业标签
        if (userFinalProfileData.getMajor_intent() != null) {
            boolean hasAdd = false;

            // 添加调试日志
            log.debug("意向专业标签判断 - 专业ID: {}, 专业类ID: {}",
                    majorDetail.getMajorId(), majorDetail.getSubCategoryId());
            log.debug("用户意向专业 - Level3: {}, Level2: {}",
                    userFinalProfileData.getMajor_intent().getLevel3_code(),
                    userFinalProfileData.getMajor_intent().getLevel2_code());

            // 检查三级专业代码匹配
            if (userFinalProfileData.getMajor_intent().getLevel3_code() != null
                    && !userFinalProfileData.getMajor_intent().getLevel3_code().isEmpty()
                    && majorDetail.getMajorId() != null) {

                if (userFinalProfileData.getMajor_intent().getLevel3_code().contains(majorDetail.getMajorId())) {
                    hasAdd = true;
                    tags.add("意向专业");
                    log.debug("匹配到意向专业: {}", majorDetail.getMajorId());
                }
            }

            // 检查二级专业代码匹配（仅在三级未匹配时）
            if (userFinalProfileData.getMajor_intent().getLevel2_code() != null
                    && !userFinalProfileData.getMajor_intent().getLevel2_code().isEmpty()
                    && majorDetail.getSubCategoryId() != null
                    && !hasAdd) {

                if (userFinalProfileData.getMajor_intent().getLevel2_code().contains(majorDetail.getSubCategoryId())) {
                    tags.add("意向专业类");
                    log.debug("匹配到意向专业类: {}", majorDetail.getSubCategoryId());
                }
            }
        } else {
            log.info("用户意向专业数据为空");
        }
        //非意向专业
        if (userFinalProfileData.getNegative_major_intent() != null) {
            boolean hasAdd = false;
            // 检查三级专业代码匹配-非意向
            if (userFinalProfileData.getNegative_major_intent().getLevel3_code() != null
                    && !userFinalProfileData.getNegative_major_intent().getLevel3_code().isEmpty()
                    && majorDetail.getMajorId() != null) {

                if (userFinalProfileData.getNegative_major_intent().getLevel3_code().contains(majorDetail.getMajorId())) {
                    hasAdd = true;
                    tags.add("负向专业");
                    log.debug("匹配到负向专业: {}", majorDetail.getMajorId());
                }
            }
            // 检查二级专业代码匹配（仅在三级未匹配时）-非意向
            if (userFinalProfileData.getNegative_major_intent().getLevel2_code() != null
                    && !userFinalProfileData.getNegative_major_intent().getLevel2_code().isEmpty()
                    && majorDetail.getSubCategoryId() != null
                    && !hasAdd) {

                if (userFinalProfileData.getNegative_major_intent().getLevel2_code().contains(majorDetail.getSubCategoryId())) {
                    tags.add("负向专业类");
                    log.debug("匹配到负向专业类: {}", majorDetail.getSubCategoryId());
                }
            }
        } else {
            log.info("用户负向专业数据为空");
        }


        return tags;
    }

    private List<String> buildSchoolPopTagList(VolunteerRecommendListResponse.VolunteerSchool school) {
        List<String> tags = Lists.newArrayList();
         if(school.getBaoyan_ratio()!=null&& school.getBaoyan_ratio() > 0) {
             tags.add("保研率：" + school.getBaoyan_ratio() + "%");
         }
        if(school.getUpgrade_ratio()!=null&& school.getUpgrade_ratio() > 0) {
            tags.add("升学率：" + school.getUpgrade_ratio() + "%");
        }
        if(school.getMaster_count()!=null&& school.getMaster_count() > 0) {
            tags.add("硕士点：" + school.getMaster_count());
        }
        if(school.getDoctor_count()!=null&& school.getDoctor_count() > 0) {
            tags.add("博士点：" + school.getDoctor_count());
        }
        return tags.stream().filter(Objects::nonNull).collect(Collectors.toList());

    }

    private List<String> buildSchoolBasicTagList(VolunteerRecommendListResponse.VolunteerSchool school) {
        List<String> tags = Lists.newArrayList();
        String address = school.getProvince_name() + "." + school.getCity_name();
        tags.add(address);
        tags.add(school.getSchool_batch());
        tags.add(school.getSchool_nature());
        tags.add(school.getSchool_category());
        tags.add(school.getSchool_level());
        return tags.stream().filter(Objects::nonNull).collect(Collectors.toList());

    }

    private List<String> buildSchoolRankTagList(VolunteerSchoolGroup detail,
                                                SchoolProfileDto schoolProfile,
                                                UserProfileData userFinalProfileData) {

        List<String> tags = Lists.newArrayList();
        if (detail.getSchoolRank() != null && detail.getSchoolRank() > 0) {
            tags.add("院校排名:" + detail.getSchoolRank());
        }
        //判断意向院校、意向地域标签（新结构）
        if (userFinalProfileData.getCollege_info() != null
                && userFinalProfileData.getCollege_info().getValues_code() != null) {
            if (userFinalProfileData.getCollege_info().getValues_code().contains(detail.getSchoolId())) {
                tags.add("意向院校");
            }
        }
        if (userFinalProfileData.getCity_info() != null
                && userFinalProfileData.getCity_info().getProvince_code() != null) {
            if (userFinalProfileData.getCity_info().getProvince_code().contains(detail.getProvinceId())) {
                tags.add("意向省份");
            }
        }
        if (userFinalProfileData.getCity_info() != null
                && userFinalProfileData.getCity_info().getCity_code() != null) {
            if (userFinalProfileData.getCity_info().getCity_code().contains(detail.getCityId())) {
                tags.add("意向城市");
            }
        }
        //判断非意向院校、地域（新结构）
        if (userFinalProfileData.getNegative_college_info() != null
                && userFinalProfileData.getNegative_college_info().getValues_code() != null) {
            if (userFinalProfileData.getNegative_college_info().getValues_code().contains(detail.getSchoolId())) {
                tags.add("负向院校");
            }
        }
        if (userFinalProfileData.getNegative_city_info() != null
                && userFinalProfileData.getNegative_city_info().getProvince_code() != null) {
            if (userFinalProfileData.getNegative_city_info().getProvince_code().contains(detail.getProvinceId())) {
                tags.add("负向省份");
            }
        }
        if (userFinalProfileData.getNegative_city_info() != null
                && userFinalProfileData.getNegative_city_info().getCity_code() != null) {
            if (userFinalProfileData.getNegative_city_info().getCity_code().contains(detail.getCityId())) {
                tags.add("负向城市");
            }
        }

        if (schoolProfile != null) {
            String honor = schoolProfile.getLegacyHonor();
            //提取两电一邮这种标签
            if (!Strings.isNullOrEmpty(honor)) {
                tags.addAll(Splitter.on("、").trimResults().splitToList(honor));
            }
        }
        return tags.stream().filter(Objects::nonNull).collect(Collectors.toList());
    }

    /**
     * 构建学校算法标签Map
     * 基于院校评估指标生成算法标签
     *
     * @param detail        学校详情
     * @param schoolProfile 学校画像
     * @return 算法标签Map
     */
    private Map<String, Object> buildSchoolAlgTagMap(VolunteerSchoolGroup detail, SchoolProfileDto schoolProfile) {
        Map<String, Object> tags = Maps.newHashMap();

        // 省份GDP指数
        if (detail.getProvince_gdp() != null) {
            tags.put("province_gdp", detail.getProvince_gdp());
        }

        // 城市等级指数
        if (detail.getCity_level() != null) {
            tags.put("city_level", detail.getCity_level());
        }

        // 考研率指数
        if (detail.getUpgrade_ratio() != null) {
            tags.put("upgrade_ratio", detail.getUpgrade_ratio());
        }

        // 保研率指数
        if (detail.getPostgraduate_recommend_ratio() != null) {
            tags.put("postgraduate_recommend_ratio", detail.getPostgraduate_recommend_ratio());
        }

        // 院校排名指数
        if (detail.getGaotu_rank() != null) {
            tags.put("gaotu_rank", detail.getGaotu_rank());
        }

        // 院校等级指数
        if (detail.getLevel_score() != null) {
            tags.put("level_score", detail.getLevel_score());
        }

        // 院校原始得分
        if (detail.getCollege_score_old() != null) {
            tags.put("college_score_old", detail.getCollege_score_old());
        }

        // 院校最终得分
        if (detail.getCollege_score_new() != null) {
            tags.put("college_score_new", detail.getCollege_score_new());
        }

        // 院校得分调整说明（旧通道：拼好的中文串，前端/导出在用）
        if (detail.getCollege_remark() != null && !detail.getCollege_remark().trim().isEmpty()) {
            tags.put("college_remark", detail.getCollege_remark());
        }

        // 院校得分调整理由（新通道：结构化，供对话层消费；P1d）
        if (detail.getCollegeReasons() != null && !detail.getCollegeReasons().isEmpty()) {
            tags.put("college_reasons", detail.getCollegeReasons());
        }

        // 志愿得分
        if (detail.getVolunteer_score() != null) {
            tags.put("volunteer_score", detail.getVolunteer_score());
        }
        if (detail.getMajor_score() != null) {
            tags.put("major_score", detail.getMajor_score());
        }

        return tags;
    }

    /**
     * 构建专业算法标签Map
     * 基于专业评估指标生成算法标签
     *
     * @param majorDetail 专业详情
     * @return 算法标签Map
     */
    private Map<String, Object> buildMajorAlgTagMap(VolunteerMajor majorDetail) {
        Map<String, Object> tags = Maps.newHashMap();

        // 性别指数
        if (majorDetail.getGender_index() != null) {
            tags.put("gender_index", majorDetail.getGender_index());
        }

        // 专业满意度指数
        if (majorDetail.getSatisfy_index() != null) {
            tags.put("satisfy_index", majorDetail.getSatisfy_index());
        }

        // 平均薪酬指数
        if (majorDetail.getSalary_avg() != null) {
            tags.put("salary_avg", majorDetail.getSalary_avg());
        }

        // 专业热度指数
        if (majorDetail.getHot_index() != null) {
            tags.put("hot_index", majorDetail.getHot_index());
        }

        // 学科评估得分
        if (majorDetail.getEvaluate_score() != null) {
            tags.put("evaluate_score", majorDetail.getEvaluate_score());
        }

        // 特色专业得分
        if (majorDetail.getSpecial_score() != null) {
            tags.put("special_score", majorDetail.getSpecial_score());
        }

        // 硕博点得分
        if (majorDetail.getDegree_score() != null) {
            tags.put("degree_score", majorDetail.getDegree_score());
        }

        // 专业（类）原始得分
        if (majorDetail.getMajor_score_old() != null) {
            tags.put("major_score_old", majorDetail.getMajor_score_old());
        }

        // 专业（类）最终得分
        if (majorDetail.getMajor_score_new() != null) {
            tags.put("major_score_new", majorDetail.getMajor_score_new());
        }

        // 专业（类）得分调整说明
        if (majorDetail.getMajor_remark() != null && !majorDetail.getMajor_remark().trim().isEmpty()) {
            tags.put("major_remark", majorDetail.getMajor_remark());
        }

        return tags;
    }
}
