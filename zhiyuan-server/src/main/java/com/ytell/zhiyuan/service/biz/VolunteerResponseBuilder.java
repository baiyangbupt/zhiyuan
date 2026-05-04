package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.util.ApplyTypeUtil;
import com.ytell.zhiyuan.common.util.ExcelUtil;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.SchoolRecommendResponse;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * 志愿响应构建器
 * 负责构建志愿相关的响应数据
 */
@Slf4j
@Component
public class VolunteerResponseBuilder {


    @Autowired
    private VolunteerUtils volunteerUtils;

    @Autowired
    private VolunteerRecommendBuilder volunteerRecommendBuilder;

    @Autowired
    private SchoolManager schoolManager;

    /**
     * 构建志愿推荐响应数据
     *
     * @param sortedIntervalData  排序后的区间数据
     * @param userScoreDetail     用户分数详情
     * @param applyType           申请类型
     * @param threeTargetCountMap 三大区间目标数量映射
     * @return 志愿推荐响应
     */
    public VolunteerRecommendListResponse buildVolunteerRecommendResponse(
            Map<String, List<VolunteerSchoolGroup>> sortedIntervalData,
            CreateSessionReq userScoreDetail,
            UserProfileData userFinalProfileData,
            String applyType,
            Map<String, Integer> threeTargetCountMap) {
        //TODO 新的数据结构适应前端展示

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserFinalProfileData(userFinalProfileData);
        response.setUserScoreDetail(userScoreDetail);
        VolunteerRecommendListResponse.BaseData baseData = new VolunteerRecommendListResponse.BaseData();

        // 区间数据转换为响应格式，按志愿等级分别构建列表
        List<VolunteerRecommendListResponse.VolunteerSchool> sprints = new ArrayList<>();
        List<VolunteerRecommendListResponse.VolunteerSchool> safes = new ArrayList<>();
        List<VolunteerRecommendListResponse.VolunteerSchool> protects = new ArrayList<>();

        // 处理冲区间数据
        List<VolunteerSchoolGroup> sprintData = sortedIntervalData.get("冲");
        if (sprintData != null) {
            sprints = sprintData.stream()
                    .map(one -> volunteerRecommendBuilder.buildVolunteerSchoolFromDetail(one, userFinalProfileData))
                    .collect(Collectors.toList());
        }

        // 处理稳区间数据
        List<VolunteerSchoolGroup> safeData = sortedIntervalData.get("稳");
        if (safeData != null) {
            safes = safeData.stream()
                    .map(one -> volunteerRecommendBuilder.buildVolunteerSchoolFromDetail(one, userFinalProfileData))
                    .collect(Collectors.toList());
        }

        // 处理保区间数据
        List<VolunteerSchoolGroup> protectData = sortedIntervalData.get("保");
        if (protectData != null) {
            protects = protectData.stream()
                    .map(one -> volunteerRecommendBuilder.buildVolunteerSchoolFromDetail(one, userFinalProfileData))
                    .collect(Collectors.toList());
        }

        // 构建基础数据
        baseData.setTarget_type(userScoreDetail.getTargetType());
        baseData.setThree_target_count_map(convertThreeTargetCountMap(threeTargetCountMap));
        baseData.setReportName("我的志愿表");
        baseData.setUserInfoSummary(volunteerUtils.getSessionExtraSummaryData(userScoreDetail));
        baseData.setVolunteerCount(userScoreDetail.getVolunteerCount());
        baseData.setVolunteerModel(userScoreDetail.getVolunteerModel());
        baseData.setPrepareType(userScoreDetail.getPrepareType());

        // 学费区间：当前会话生效中的区间直接来自 userScoreDetail
        baseData.setTuitionRange(userScoreDetail.getTuitionRange() == null ? new CreateSessionReq.TuitionRange(0, 100000) : userScoreDetail.getTuitionRange());

        // 学费区间配置：暂定一个较宽的默认区间和步长，后续可根据省份/批次做个性化
        VolunteerRecommendListResponse.TuitionRangeConfig tuitionRangeConfig = new VolunteerRecommendListResponse.TuitionRangeConfig();
        tuitionRangeConfig.setMin(0);
        tuitionRangeConfig.setMax(100000);
        tuitionRangeConfig.setStep(1000);
        baseData.setTuitionRangeConfig(tuitionRangeConfig);

        // 设置各区间录取率范围
        baseData.setSprints_enroll_ratio(Arrays.asList("1%", "50%"));
        baseData.setSafes_enroll_ratio(Arrays.asList("51%", "70%"));
        baseData.setProtects_enroll_ratio(Arrays.asList("71%", "99%"));

        // 设置各区间数量统计
        setIntervalCounts(baseData, sprints, safes, protects, applyType, userScoreDetail);

        // 构建响应
        response.setBaseData(baseData);
        response.setSprints(sprints);
        response.setSafes(safes);
        response.setProtects(protects);
        response.setMajorSchoolType(ApplyTypeUtil.isMajorSchoolType(applyType));

        // 标记优选排名
        Map<String, Integer> targetMap = baseData.getThree_target_count_map();
        if (targetMap != null) {
            markPreferredSchools(sprints, targetMap.getOrDefault("sprints_count", 0));
            markPreferredSchools(safes, targetMap.getOrDefault("safes_count", 0));
            markPreferredSchools(protects, targetMap.getOrDefault("protects_count", 0));
        }

        return response;
    }

    /**
     * 标记优选志愿：按 volunteer_score 降序排名，waterline 以内标记为优选
     */
    private void markPreferredSchools(List<VolunteerRecommendListResponse.VolunteerSchool> schools, int waterline) {
        if (schools == null || schools.isEmpty()) {
            return;
        }
        // 按 volunteer_score 降序排名（不改变原列表顺序）
        List<VolunteerRecommendListResponse.VolunteerSchool> sorted = new ArrayList<>(schools);
        sorted.sort((a, b) -> Double.compare(getVolunteerScore(b), getVolunteerScore(a)));

        Map<VolunteerRecommendListResponse.VolunteerSchool, Integer> rankMap = new java.util.IdentityHashMap<>();
        for (int i = 0; i < sorted.size(); i++) {
            rankMap.put(sorted.get(i), i + 1);
        }
        for (VolunteerRecommendListResponse.VolunteerSchool s : schools) {
            int rank = rankMap.getOrDefault(s, schools.size());
            s.setRank_in_tier(rank);
            s.setIs_preferred(rank <= waterline);
        }
    }

    private double getVolunteerScore(VolunteerRecommendListResponse.VolunteerSchool school) {
        if (school.getAlgTagMap() == null) return 0;
        Object val = school.getAlgTagMap().get("volunteer_score");
        return val instanceof Number ? ((Number) val).doubleValue() : 0;
    }

    /**
     * 设置各区间数量统计
     */
    private void setIntervalCounts(VolunteerRecommendListResponse.BaseData baseData,
                                   List<VolunteerRecommendListResponse.VolunteerSchool> sprints,
                                   List<VolunteerRecommendListResponse.VolunteerSchool> safes,
                                   List<VolunteerRecommendListResponse.VolunteerSchool> protects,
                                   String applyType,
                                   CreateSessionReq userScoreDetail) {

        if (ApplyTypeUtil.isMajorSchoolType(applyType)) {
            // 专业+院校做了学校聚合，因此计算数量的时候需要计算专业的数量
            Integer sprintTotal = sprints.stream().mapToInt(one -> one.getMajors().size()).sum();
            Integer safeTotal = safes.stream().mapToInt(one -> one.getMajors().size()).sum();
            Integer protectTotal = protects.stream().mapToInt(one -> one.getMajors().size()).sum();
            baseData.setSprints_count(sprintTotal);
            baseData.setSafes_count(safeTotal);
            baseData.setProtects_count(protectTotal);
            baseData.setNeed_count(userScoreDetail.getVolunteerCount().getMajorCount());
        } else {
            baseData.setSprints_count(sprints.size());
            baseData.setSafes_count(safes.size());
            baseData.setProtects_count(protects.size());
            baseData.setNeed_count(userScoreDetail.getVolunteerCount().getSchoolCount());
        }

        baseData.setTotal_count(baseData.getSprints_count() + baseData.getProtects_count() + baseData.getSafes_count());
    }

    /**
     * 转换三大目标数量映射
     */
    public Map<String, Integer> convertThreeTargetCountMap(Map<String, Integer> threeTargetCountMap) {
        Map<String, Integer> after = Maps.newHashMap();
        after.put("sprints_count", threeTargetCountMap.getOrDefault("冲", 30));
        after.put("safes_count", threeTargetCountMap.getOrDefault("稳", 30));
        after.put("protects_count", threeTargetCountMap.getOrDefault("保", 30));
        return after;
    }

    /**
     * 构建学校推荐响应
     */
    public SchoolRecommendResponse buildSchoolRecommendResponse(VolunteerRecommendListResponse volunteerResponse,RecommendReq recommendReq) {

        List<SchoolRecommendResponse.SchoolInfo> schoolInfoList;
        Boolean majorSchoolType = volunteerResponse.getMajorSchoolType();

        // 1. 合并sprints、safes、protects三个列表，保持原有顺序
        List<VolunteerRecommendListResponse.VolunteerSchool> allVolunteerSchools = new ArrayList<>();
        if (volunteerResponse.getSprints() != null) {
            allVolunteerSchools.addAll(volunteerResponse.getSprints());
        }
        if (volunteerResponse.getSafes() != null) {
            allVolunteerSchools.addAll(volunteerResponse.getSafes());
        }
        if (volunteerResponse.getProtects() != null) {
            allVolunteerSchools.addAll(volunteerResponse.getProtects());
        }
        //2.概率截取
        if (recommendReq.getMinEnrollRate() != null && recommendReq.getMaxEnrollRate() != null) {
            allVolunteerSchools = allVolunteerSchools
                    .stream()
                    .filter(one -> Double.parseDouble(one.getEnroll_ratio()) >= recommendReq.getMinEnrollRate()
                            && Double.parseDouble(one.getEnroll_ratio()) <= recommendReq.getMaxEnrollRate())
                    .collect(Collectors.toList());
        }
        //院校、省份、地域、tag过滤


        //2.根据模式选择提取
        if (majorSchoolType) {
            // 专业+院校模式：从冲稳保列表按顺序截取5个学校，每个学校最多4个专业
            schoolInfoList = volunteerRecommendBuilder.extractSchoolsForMajorSchoolMode(allVolunteerSchools);
        } else {
            // 专业组模式：按照schoolId聚合专业组，保持相对顺序
            schoolInfoList = volunteerRecommendBuilder.extractSchoolsForMajorGroupMode(allVolunteerSchools);
        }

        SchoolRecommendResponse schoolRecommendResponse = new SchoolRecommendResponse();
        schoolRecommendResponse.setSchoolList(schoolInfoList);
        log.info("构建学校推荐响应完成，是否院校+专业模式：{}，总共推荐{}所学校", majorSchoolType, schoolInfoList.size());
        return schoolRecommendResponse;
    }

    /**
     * Excel数据包装类，包含主列表和候补列表
     */
    public static class ExcelDataWrapper {
        private List<ExcelUtil.VolunteerExcelData> mainList;
        private List<ExcelUtil.VolunteerExcelData> backupList;

        public ExcelDataWrapper(List<ExcelUtil.VolunteerExcelData> mainList, List<ExcelUtil.VolunteerExcelData> backupList) {
            this.mainList = mainList;
            this.backupList = backupList;
        }

        public List<ExcelUtil.VolunteerExcelData> getMainList() {
            return mainList;
        }

        public List<ExcelUtil.VolunteerExcelData> getBackupList() {
            return backupList;
        }
    }

    /**
     * 转换志愿数据为Excel数据格式（区分主列表和候补列表）
     */
    public ExcelDataWrapper convertToExcelData(VolunteerRecommendListResponse volunteerData) {
        List<ExcelUtil.VolunteerExcelData> mainExcelDataList = new ArrayList<>();
        List<ExcelUtil.VolunteerExcelData> backupExcelDataList = new ArrayList<>();

        if (volunteerData != null && volunteerData.getBaseData() != null) {
            // 获取目标个数
            Map<String, Integer> targetCountMap = volunteerData.getBaseData().getThree_target_count_map();
            int sprintTargetCount = targetCountMap.getOrDefault("sprints_count", 0);
            int safeTargetCount = targetCountMap.getOrDefault("safes_count", 0);
            int protectTargetCount = targetCountMap.getOrDefault("protects_count", 0);
            int backupCount = 15; // 候补志愿数量

            int globalIndex = 1;

            // 第一步：处理所有主列表（冲、稳、保）
            // 处理冲刺志愿主列表
            if (volunteerData.getSprints() != null) {
                List<VolunteerRecommendListResponse.VolunteerSchool> sprints = volunteerData.getSprints();
                for (int i = 0; i < Math.min(sprintTargetCount, sprints.size()); i++) {
                    ExcelUtil.VolunteerExcelData excelData = buildExcelDataFromSchool(sprints.get(i), globalIndex++);
                    if (excelData != null) {
                        mainExcelDataList.add(excelData);
                    }
                }
            }

            // 处理稳妥志愿主列表
            if (volunteerData.getSafes() != null) {
                List<VolunteerRecommendListResponse.VolunteerSchool> safes = volunteerData.getSafes();
                for (int i = 0; i < Math.min(safeTargetCount, safes.size()); i++) {
                    ExcelUtil.VolunteerExcelData excelData = buildExcelDataFromSchool(safes.get(i), globalIndex++);
                    if (excelData != null) {
                        mainExcelDataList.add(excelData);
                    }
                }
            }

            // 处理保底志愿主列表
            if (volunteerData.getProtects() != null) {
                List<VolunteerRecommendListResponse.VolunteerSchool> protects = volunteerData.getProtects();
                for (int i = 0; i < Math.min(protectTargetCount, protects.size()); i++) {
                    ExcelUtil.VolunteerExcelData excelData = buildExcelDataFromSchool(protects.get(i), globalIndex++);
                    if (excelData != null) {
                        mainExcelDataList.add(excelData);
                    }
                }
            }

            // 第二步：处理所有候补列表（冲、稳、保），序号从主列表的序号+1开始
            // 处理冲刺志愿候补列表
            if (volunteerData.getSprints() != null) {
                List<VolunteerRecommendListResponse.VolunteerSchool> sprints = volunteerData.getSprints();
                int backupStart = sprintTargetCount;
                int backupEnd = Math.min(backupStart + backupCount, sprints.size());
                for (int i = backupStart; i < backupEnd; i++) {
                    ExcelUtil.VolunteerExcelData excelData = buildExcelDataFromSchool(sprints.get(i), globalIndex++);
                    if (excelData != null) {
                        backupExcelDataList.add(excelData);
                    }
                }
            }

            // 处理稳妥志愿候补列表
            if (volunteerData.getSafes() != null) {
                List<VolunteerRecommendListResponse.VolunteerSchool> safes = volunteerData.getSafes();
                int backupStart = safeTargetCount;
                int backupEnd = Math.min(backupStart + backupCount, safes.size());
                for (int i = backupStart; i < backupEnd; i++) {
                    ExcelUtil.VolunteerExcelData excelData = buildExcelDataFromSchool(safes.get(i), globalIndex++);
                    if (excelData != null) {
                        backupExcelDataList.add(excelData);
                    }
                }
            }

            // 处理保底志愿候补列表
            if (volunteerData.getProtects() != null) {
                List<VolunteerRecommendListResponse.VolunteerSchool> protects = volunteerData.getProtects();
                int backupStart = protectTargetCount;
                int backupEnd = Math.min(backupStart + backupCount, protects.size());
                for (int i = backupStart; i < backupEnd; i++) {
                    ExcelUtil.VolunteerExcelData excelData = buildExcelDataFromSchool(protects.get(i), globalIndex++);
                    if (excelData != null) {
                        backupExcelDataList.add(excelData);
                    }
                }
            }
        }

        return new ExcelDataWrapper(mainExcelDataList, backupExcelDataList);
    }

    /**
     * 从学校数据构建Excel数据
     */
    private ExcelUtil.VolunteerExcelData buildExcelDataFromSchool(
            VolunteerRecommendListResponse.VolunteerSchool school, int index) {
        SchoolVO schoolVO = schoolManager.getSchoolById(school.getSchoolId());
        ExcelUtil.VolunteerExcelData excelData = new ExcelUtil.VolunteerExcelData();

        excelData.setIndex(index);
        excelData.setEnrollRatio(school.getEnroll_ratio());
        excelData.setSchoolCode(school.getSchoolUnitCode());
        excelData.setSchoolName(school.getSchool_name());
        if (schoolVO != null) {
            excelData.setSchoolLevel(schoolVO.getSchoolTags());
            // 安全处理省份和城市拼接
            String province = schoolVO.getProvince() != null ? schoolVO.getProvince() : "";
            String city = schoolVO.getCity() != null ? schoolVO.getCity() : "";
            excelData.setSchoolPosition(province + city);
            excelData.setSchoolType(schoolVO.getSchoolType());
            // 安全处理办学层次和性质拼接
            String educationLevel = schoolVO.getEducationLevel() != null ? schoolVO.getEducationLevel() : "";
            String ownership = schoolVO.getOwnership() != null ? schoolVO.getOwnership() : "";
            excelData.setSchoolNature(educationLevel + ownership);
        }
        // 安全处理学校排名
        excelData.setSchoolRank(school.getSchool_rank() != null ? String.valueOf(school.getSchool_rank()) : "");

        // 构建专业列表
        List<ExcelUtil.VolunteerMajorExcelData> majorList = new ArrayList<>();
        if (school.getMajors() != null) {
            for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                if (major != null) {
                    ExcelUtil.VolunteerMajorExcelData majorData = buildExcelMajorDataFromMajor(major);
                    if (majorData != null) {
                        majorList.add(majorData);
                    }
                }
            }
        }

        excelData.setMajorList(majorList);
        return excelData;
    }

    /**
     * 从专业数据构建Excel专业数据
     */
    private ExcelUtil.VolunteerMajorExcelData buildExcelMajorDataFromMajor(
            VolunteerRecommendListResponse.VolunteerMajor major) {

        ExcelUtil.VolunteerMajorExcelData majorData = new ExcelUtil.VolunteerMajorExcelData();
        majorData.setMajorCode(major.getMajorUnitCode());
        majorData.setMajorName(major.getMajor_name());

        // 录取率
        majorData.setMajorEnrollRatio(major.getEnroll_ratio() != null ? major.getEnroll_ratio() + "%" : "");

        // 计划数
        majorData.setMajorPlan(major.getPlanNum() != null ? String.valueOf(major.getPlanNum()) : null);

        // 选科
        majorData.setMajorSelectInfo(
                Optional.ofNullable(major.getMust_subject())
                        .filter(list -> !list.isEmpty())
                        .map(list -> list.get(0))
                        .orElse("")
        );

        // 专业学费
        majorData.setMajorTuition(major.getPlanMoney());

        // 专业学制
        majorData.setMajorDuration(major.getDuration());

        // 历史数据处理
        if (major.getHistory_score_list() != null && !major.getHistory_score_list().isEmpty()) {
            // 去年的数据
            if (major.getHistory_score_list().size() > 0) {
                VolunteerRecommendListResponse.HistoryScore lastYear = major.getHistory_score_list().get(0);
                if (lastYear != null) {
                    majorData.setMajorEnrollNumLastYear(volunteerUtils.emptyNumValue(lastYear.getEnrollNum() != null ? String.valueOf(lastYear.getEnrollNum()) : "-"));
                    majorData.setMajorMinScoreLastYear(volunteerUtils.emptyNumValue(lastYear.getScore() != null ? String.valueOf(lastYear.getScore()) : "-"));
                    majorData.setMajorMinPosLastYear(volunteerUtils.emptyNumValue(lastYear.getPos() != null ? String.valueOf(lastYear.getPos()) : "-"));
                }
            }

            // 前年的数据
            if (major.getHistory_score_list().size() > 1) {
                VolunteerRecommendListResponse.HistoryScore yearBefore = major.getHistory_score_list().get(1);
                if (yearBefore != null) {
                    majorData.setMajorEnrollNumYearBefore(volunteerUtils.emptyNumValue(yearBefore.getEnrollNum() != null ? String.valueOf(yearBefore.getEnrollNum()) : "-"));
                    majorData.setMajorMinScoreYearBefore(volunteerUtils.emptyNumValue(yearBefore.getScore() != null ? String.valueOf(yearBefore.getScore()) : "-"));
                    majorData.setMajorMinPosYearBefore(volunteerUtils.emptyNumValue(yearBefore.getPos() != null ? String.valueOf(yearBefore.getPos()) : "-"));
                }
            }

            // 大前年的数据
            if (major.getHistory_score_list().size() > 2) {
                VolunteerRecommendListResponse.HistoryScore yearBeforeLast = major.getHistory_score_list().get(2);
                if (yearBeforeLast != null) {
                    majorData.setMajorEnrollNumYearBeforeLast(volunteerUtils.emptyNumValue(yearBeforeLast.getEnrollNum() != null ? String.valueOf(yearBeforeLast.getEnrollNum()) : "-"));
                    majorData.setMajorMinScoreYearBeforeLast(volunteerUtils.emptyNumValue(yearBeforeLast.getScore() != null ? String.valueOf(yearBeforeLast.getScore()) : "-"));
                    majorData.setMajorMinPosYearBeforeLast(volunteerUtils.emptyNumValue(yearBeforeLast.getPos() != null ? String.valueOf(yearBeforeLast.getPos()) : "-"));
                }
            }
        }

        return majorData;
    }
}
