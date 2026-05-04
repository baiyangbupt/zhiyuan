package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.config.VolunteerAnalysisConfig;
import com.ytell.zhiyuan.manager.rank.VolunteerRankClient;
import com.ytell.zhiyuan.model.dto.*;
import com.ytell.zhiyuan.model.dto.inner.*;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Slf4j
@Service
public class VolunteerAnalysisBizService {

    @Autowired
    private VolunteerBizService volunteerBizService;
    @Autowired
    private VolunteerRankClient volunteerRankClient;
    @Autowired
    private VolunteerDataProvider dataProvider;
    @Autowired
    private VolunteerUtils utils;
    @Autowired
    private VolunteerAnalysisConfig analysisConfig;

    public MajorAnalysisRes analyseMajor(Long chatSessionId, MajorAnalysisReq majorAnalysisReq) {
        MajorAnalysisRes res = new MajorAnalysisRes();
        List<MajorAnalysisRes.MajorAnalysis> majorAnalyseList = Lists.newArrayList();
        res.setMajorAnalyseList(majorAnalyseList);

        VolunteerRecommendListResponse volunteerRecommendListResponse = volunteerBizService.loadCachedRecommendData(chatSessionId);
        List<MajorAnalysisReq.MajorItem> majorItemList = majorAnalysisReq.getMajorItemList();

        for (MajorAnalysisReq.MajorItem majorItem : majorItemList) {
            MajorAnalysisRes.MajorAnalysis analysis = analyseSingleMajor(chatSessionId, majorItem, volunteerRecommendListResponse);
            majorAnalyseList.add(analysis);
        }

        return res;
    }

    /**
     * 分析单个专业
     */
    private MajorAnalysisRes.MajorAnalysis analyseSingleMajor(Long chatSessionId, MajorAnalysisReq.MajorItem majorItem,
                                                              VolunteerRecommendListResponse volunteerRecommendListResponse) {
        MajorAnalysisRes.MajorAnalysis analysis = new MajorAnalysisRes.MajorAnalysis();
        analysis.setId(majorItem.getId());

        // 1. 检查专业是否在推荐方案中
        List<MajorAnalysisRes.VolunteerInfo> recommendedVolunteers = findMajorInRecommendList(majorItem, volunteerRecommendListResponse);

        if (!recommendedVolunteers.isEmpty()) {
            // 专业在推荐方案中
            analysis.setInChoose(true);
            analysis.setVolunteerList(recommendedVolunteers);
            List<MajorAnalysisRes.VolunteerInfo> candidateVolunteers = findMajorInCandidates(chatSessionId, majorItem, volunteerRecommendListResponse);
            String candidateVolunteersSummary = "";
            if (!candidateVolunteers.isEmpty()) {
                candidateVolunteersSummary = generateCandidateAnalysis(majorItem.getName(), candidateVolunteers);
            }
            analysis.setSummary(generateRecommendSummary(majorItem.getName(), recommendedVolunteers) + "\n" + candidateVolunteersSummary);
        } else {
            // 专业不在推荐方案中，查找候选专业
            analysis.setInChoose(false);
            List<MajorAnalysisRes.VolunteerInfo> candidateVolunteers = findMajorInCandidates(chatSessionId, majorItem, volunteerRecommendListResponse);

            if (candidateVolunteers.isEmpty()) {
                // 没有找到合适的专业
                analysis.setVolunteerList(Lists.newArrayList());
                analysis.setSummary("您的分数区间没有找到较合适的" + majorItem.getName() + "专业志愿可以填报");
            } else {
                // 找到了候选专业，分析不被优选的原因
                analysis.setVolunteerList(candidateVolunteers);
                analysis.setSummary(generateCandidateAnalysis(majorItem.getName(), candidateVolunteers));
            }
        }

        return analysis;
    }


    /**
     * 判断是否应该继续添加志愿信息（按区间统计）
     */
    private boolean shouldContinueByLevel(List<MajorAnalysisRes.VolunteerInfo> currentList, String level) {
        if (!analysisConfig.isEnableTruncation()) {
            return true;
        }

        // 统计当前区间的志愿数量
        long currentLevelCount = currentList.stream()
                .filter(volunteer -> level.equals(volunteer.getVolunteerLevel()))
                .count();

        int maxSize;
        switch (level) {
            case "冲":
                maxSize = analysisConfig.getSprintMaxCount();
                break;
            case "稳":
                maxSize = analysisConfig.getSafeMaxCount();
                break;
            case "保":
                maxSize = analysisConfig.getProtectMaxCount();
                break;
            default:
                maxSize = Integer.MAX_VALUE;
        }

        return currentLevelCount < maxSize;
    }

    /**
     * 判断是否应该继续添加学校志愿信息（按区间统计）
     */
    private boolean shouldContinueByLevelForSchool(List<SchoolAnalysisRes.VolunteerInfo> currentList, String level) {
        if (!analysisConfig.isEnableTruncation()) {
            return true;
        }

        // 统计当前区间的学校数量（每个VolunteerInfo代表一个学校）
        long currentLevelCount = currentList.stream()
                .filter(volunteer -> level.equals(volunteer.getVolunteerLevel()))
                .count();

        int maxSize;
        switch (level) {
            case "冲":
                maxSize = analysisConfig.getSprintMaxCount();
                break;
            case "稳":
                maxSize = analysisConfig.getSafeMaxCount();
                break;
            case "保":
                maxSize = analysisConfig.getProtectMaxCount();
                break;
            default:
                maxSize = Integer.MAX_VALUE;
        }

        return currentLevelCount < maxSize;
    }

    /**
     * 在推荐列表中查找专业
     */
    private List<MajorAnalysisRes.VolunteerInfo> findMajorInRecommendList(MajorAnalysisReq.MajorItem majorItem,
                                                                          VolunteerRecommendListResponse volunteerRecommendListResponse) {
        List<MajorAnalysisRes.VolunteerInfo> volunteers = Lists.newArrayList();

        // 获取推荐数量限制
        Map<String, Integer> targetCountMap = volunteerRecommendListResponse.getBaseData().getThree_target_count_map();
        int sprintLimit = targetCountMap.getOrDefault("sprints_count", 0);
        int safeLimit = targetCountMap.getOrDefault("safes_count", 0);
        int protectLimit = targetCountMap.getOrDefault("protects_count", 0);

        // 在冲刺志愿中查找（只查找推荐范围内的）
        if (volunteerRecommendListResponse.getSprints() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> sprintSchools = volunteerRecommendListResponse.getSprints();
            for (int i = 0; i < Math.min(sprintLimit, sprintSchools.size()); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = sprintSchools.get(i);
                if (school.getMajors() != null) {
                    for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                        if (isMajorMatch(majorItem, major)) {
                            volunteers.add(buildVolunteerInfo(school, major, "冲"));
                            if (!shouldContinueByLevel(volunteers, "冲")) break;
                        }
                    }
                }
                if (!shouldContinueByLevel(volunteers, "冲")) break;
            }
        }

        // 在稳妥志愿中查找（只查找推荐范围内的）
        if (volunteerRecommendListResponse.getSafes() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> safeSchools = volunteerRecommendListResponse.getSafes();
            for (int i = 0; i < Math.min(safeLimit, safeSchools.size()); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = safeSchools.get(i);
                if (school.getMajors() != null) {
                    for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                        if (isMajorMatch(majorItem, major)) {
                            volunteers.add(buildVolunteerInfo(school, major, "稳"));
                            if (!shouldContinueByLevel(volunteers, "稳")) break;
                        }
                    }
                }
                if (!shouldContinueByLevel(volunteers, "稳")) break;
            }
        }

        // 在保底志愿中查找（只查找推荐范围内的）
        if (volunteerRecommendListResponse.getProtects() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> protectSchools = volunteerRecommendListResponse.getProtects();
            for (int i = 0; i < Math.min(protectLimit, protectSchools.size()); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = protectSchools.get(i);
                if (school.getMajors() != null) {
                    for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                        if (isMajorMatch(majorItem, major)) {
                            volunteers.add(buildVolunteerInfo(school, major, "保"));
                            if (!shouldContinueByLevel(volunteers, "保")) break;
                        }
                    }
                }
                if (!shouldContinueByLevel(volunteers, "保")) break;
            }
        }

        return volunteers;
    }

    /**
     * 在候选专业中查找
     * 查找超出推荐范围的专业（候补专业）
     */
    private List<MajorAnalysisRes.VolunteerInfo> findMajorInCandidates(Long chatSessionId, MajorAnalysisReq.MajorItem majorItem,
                                                                       VolunteerRecommendListResponse volunteerRecommendListResponse) {
        List<MajorAnalysisRes.VolunteerInfo> candidates = Lists.newArrayList();

        // 获取推荐数量限制
        Map<String, Integer> targetCountMap = volunteerRecommendListResponse.getBaseData().getThree_target_count_map();
        int sprintLimit = targetCountMap.getOrDefault("sprints_count", 0);
        int safeLimit = targetCountMap.getOrDefault("safes_count", 0);
        int protectLimit = targetCountMap.getOrDefault("protects_count", 0);

        // 在冲刺志愿的候补部分中查找
        if (volunteerRecommendListResponse.getSprints() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> sprintSchools = volunteerRecommendListResponse.getSprints();
            for (int i = sprintLimit; i < sprintSchools.size(); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = sprintSchools.get(i);
                if (school.getMajors() != null) {
                    for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                        if (isMajorMatch(majorItem, major)) {
                            candidates.add(buildVolunteerInfo(school, major, "冲"));
                            if (!shouldContinueByLevel(candidates, "冲")) break;
                        }
                    }
                }
                if (!shouldContinueByLevel(candidates, "冲")) break;
            }
        }

        // 在稳妥志愿的候补部分中查找
        if (volunteerRecommendListResponse.getSafes() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> safeSchools = volunteerRecommendListResponse.getSafes();
            for (int i = safeLimit; i < safeSchools.size(); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = safeSchools.get(i);
                if (school.getMajors() != null) {
                    for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                        if (isMajorMatch(majorItem, major)) {
                            candidates.add(buildVolunteerInfo(school, major, "稳"));
                            if (!shouldContinueByLevel(candidates, "稳")) break;
                        }
                    }
                }
                if (!shouldContinueByLevel(candidates, "稳")) break;
            }
        }

        // 在保底志愿的候补部分中查找
        if (volunteerRecommendListResponse.getProtects() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> protectSchools = volunteerRecommendListResponse.getProtects();
            for (int i = protectLimit; i < protectSchools.size(); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = protectSchools.get(i);
                if (school.getMajors() != null) {
                    for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                        if (isMajorMatch(majorItem, major)) {
                            candidates.add(buildVolunteerInfo(school, major, "保"));
                            if (!shouldContinueByLevel(candidates, "保")) break;
                        }
                    }
                }
                if (!shouldContinueByLevel(candidates, "保")) break;
            }
        }

        return candidates;
    }

    /**
     * 判断专业是否匹配
     */
    private boolean isMajorMatch(MajorAnalysisReq.MajorItem majorItem, VolunteerRecommendListResponse.VolunteerMajor major) {
        // 匹配专业名称
        if (majorItem.getName() != null && major.getMajor_name()!=null) {
           if(major.getMajor_name().contains(majorItem.getName())) {
               return true;
           }
        }

        // 根据level匹配对应的ID字段
        if (majorItem.getId() != null) {
            Integer level = majorItem.getLevel();
            // 如果没有level信息，默认为三级专业
            if (level == null) {
                level = 3;
            }

            switch (level) {
                case 1:
                    // level = 1: 专业ID (categoryId)
                    return majorItem.getId().equals(major.getCategoryId());
                case 2:
                    // level = 2: 专业类别ID (subCategoryId)
                    return majorItem.getId().equals(major.getSubCategoryId());
                case 3:
                    // level = 3: 专业子类别ID (majorId)
                    return majorItem.getId().equals(major.getMajorId());
                default:
                    // 其他情况默认为三级专业
                    return majorItem.getId().equals(major.getMajorId());
            }
        }

        return false;
    }


    /**
     * 构建志愿信息
     */
    private MajorAnalysisRes.VolunteerInfo buildVolunteerInfo(VolunteerRecommendListResponse.VolunteerSchool school,
                                                              VolunteerRecommendListResponse.VolunteerMajor major,
                                                              String level) {
        MajorAnalysisRes.VolunteerInfo volunteerInfo = new MajorAnalysisRes.VolunteerInfo();
        volunteerInfo.setSchoolName(school.getSchool_name());
        volunteerInfo.setMajorName(major.getMajor_name());
        volunteerInfo.setVolunteerLevel(level);
        volunteerInfo.setEnrollRate(major.getEnroll_ratio());
        volunteerInfo.setWeightInfo(major.getAlgTagMap());
        return volunteerInfo;
    }

    /**
     * 生成推荐专业总结
     */
    private String generateRecommendSummary(String majorName, List<MajorAnalysisRes.VolunteerInfo> volunteers) {
        StringBuilder summary = new StringBuilder();
        summary.append("该专业在您的推荐方案中，为您推荐以下").append(volunteers.size()).append("个相关志愿：\n");

        for (MajorAnalysisRes.VolunteerInfo volunteer : volunteers) {
            summary.append("• ").append(volunteer.getSchoolName()).append(" - ")
                    .append(volunteer.getMajorName()).append(" (")
                    .append(volunteer.getVolunteerLevel()).append("档，录取率：")
                    .append(volunteer.getEnrollRate()).append("%)\n");
        }

        return summary.toString();
    }

    /**
     * 生成候选专业分析
     */
    private String generateCandidateAnalysis(String majorName, List<MajorAnalysisRes.VolunteerInfo> volunteers) {
        StringBuilder summary = new StringBuilder();
        summary.append("在候补志愿中为您找到").append(volunteers.size()).append("个相关志愿。\n");

        // 分析权重因素
        List<String> lowFactors = analyzeLowWeightFactors(volunteers);
        if (!lowFactors.isEmpty()) {
            summary.append("分析原因：该专业在以下维度权重较低：\n");
            for (String factor : lowFactors) {
                summary.append("• ").append(factor).append("\n");
            }
        } else {
            summary.append("分析原因：专业热度较低，就业及综合评价相对不高，导致相对匹配度较低。\n");
        }

        summary.append("建议：是否考虑将该专业加入专业意向来提高专业优先级？");

        return summary.toString();
    }

    /**
     * 分析权重较低的因素
     */
    private List<String> analyzeLowWeightFactors(List<MajorAnalysisRes.VolunteerInfo> volunteers) {
        List<String> factors = Lists.newArrayList();

        for (MajorAnalysisRes.VolunteerInfo volunteer : volunteers) {
            Object weightInfoObj = volunteer.getWeightInfo();
            if (weightInfoObj instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> weightInfo = (Map<String, Object>) weightInfoObj;

                // 检查专业热度
                Object hotIndex = weightInfo.get("hot_index");
                if (hotIndex instanceof Double && (Double) hotIndex < 0.5) {
                    factors.add("专业热度较低");
                }

                // 检查满意度
                Object satisfyIndex = weightInfo.get("satisfy_index");
                if (satisfyIndex instanceof Double && (Double) satisfyIndex < 0.5) {
                    factors.add("专业满意度较低");
                }

                // 检查薪酬
                Object salaryAvg = weightInfo.get("salary_avg");
                if (salaryAvg instanceof Double && (Double) salaryAvg < 0.5) {
                    factors.add("平均薪酬相对较低");
                }

                // 检查专业得分
                Object majorScore = weightInfo.get("major_score_final");
                if (majorScore instanceof Double && (Double) majorScore < 0.6) {
                    factors.add("综合专业得分较低");
                }

                // 检查学科评估得分
                Object evaluateScore = weightInfo.get("evaluate_score");
                if (evaluateScore instanceof Integer && (Integer) evaluateScore < 3) {
                    factors.add("学科评估等级较低");
                }

                // 检查特色专业得分
                Object specialScore = weightInfo.get("special_score");
                if (specialScore instanceof Integer && (Integer) specialScore < 3) {
                    factors.add("特色专业建设较弱");
                }
            }
        }

        return factors;
    }

    public SchoolAnalysisRes analyseSchool(Long chatSessionId, SchoolAnalysisReq schoolAnalysisReq) {
        SchoolAnalysisRes res = new SchoolAnalysisRes();
        List<SchoolAnalysisRes.SchoolAnalysis> schoolAnalyses = Lists.newArrayList();
        res.setSchoolAnalyseList(schoolAnalyses);

        VolunteerRecommendListResponse volunteerRecommendListResponse = volunteerBizService.loadCachedRecommendData(chatSessionId);
        List<SchoolAnalysisReq.SchoolItem> schoolItemList = schoolAnalysisReq.getSchoolItemList();

        for (SchoolAnalysisReq.SchoolItem schoolItem : schoolItemList) {
            SchoolAnalysisRes.SchoolAnalysis analysis = analyseSingleSchool(chatSessionId, schoolItem, volunteerRecommendListResponse);
            schoolAnalyses.add(analysis);
        }

        return res;
    }

    /**
     * 分析单个学校
     */
    private SchoolAnalysisRes.SchoolAnalysis analyseSingleSchool(Long chatSessionId, SchoolAnalysisReq.SchoolItem schoolItem,
                                                                 VolunteerRecommendListResponse volunteerRecommendListResponse) {
        SchoolAnalysisRes.SchoolAnalysis analysis = new SchoolAnalysisRes.SchoolAnalysis();
        analysis.setId(schoolItem.getId());

        // 1. 检查学校是否在推荐方案中
        List<SchoolAnalysisRes.VolunteerInfo> recommendedVolunteers = findSchoolInRecommendList(schoolItem, volunteerRecommendListResponse);

        if (!recommendedVolunteers.isEmpty()) {
            // 优选志愿列表：
            String recommendedVolunteersSummary = generateSchoolRecommendSummary(schoolItem.getName(), recommendedVolunteers);
            //候补志愿列表：
            List<SchoolAnalysisRes.VolunteerInfo> candidateVolunteers = findSchoolInCandidates(chatSessionId, schoolItem, volunteerRecommendListResponse);
            String candidateVolunteersSummary = "";
            if (!candidateVolunteers.isEmpty()) {
                candidateVolunteersSummary = generateSchoolCandidateAnalysis(schoolItem.getName(), candidateVolunteers);
            }
            //返回
            analysis.setInChoose(true);
            analysis.setVolunteerList(recommendedVolunteers);
            analysis.setSummary(recommendedVolunteersSummary + "\n" + candidateVolunteersSummary);
        } else {
            // 学校不在推荐方案中，查找候补志愿
            analysis.setInChoose(false);
            List<SchoolAnalysisRes.VolunteerInfo> candidateVolunteers = findSchoolInCandidates(chatSessionId, schoolItem, volunteerRecommendListResponse);

            if (candidateVolunteers.isEmpty()) {
                // 没有找到合适的学校，分析录取概率
                analysis.setVolunteerList(Lists.newArrayList());
                analysis.setSummary(analyzeSchoolAdmissionProbability(schoolItem.getName(), volunteerRecommendListResponse));
            } else {
                // 找到了候补学校，分析不被优选的原因
                analysis.setVolunteerList(candidateVolunteers);
                analysis.setSummary(generateSchoolCandidateAnalysis(schoolItem.getName(), candidateVolunteers));
            }
        }

        return analysis;
    }

    /**
     * 在推荐列表中查找学校
     */
    private List<SchoolAnalysisRes.VolunteerInfo> findSchoolInRecommendList(SchoolAnalysisReq.SchoolItem schoolItem,
                                                                            VolunteerRecommendListResponse volunteerRecommendListResponse) {
        List<SchoolAnalysisRes.VolunteerInfo> volunteers = Lists.newArrayList();

        // 获取推荐数量限制
        Map<String, Integer> targetCountMap = volunteerRecommendListResponse.getBaseData().getThree_target_count_map();
        int sprintLimit = targetCountMap.getOrDefault("sprints_count", 0);
        int safeLimit = targetCountMap.getOrDefault("safes_count", 0);
        int protectLimit = targetCountMap.getOrDefault("protects_count", 0);

        // 在冲刺志愿中查找（只查找推荐范围内的）
        if (volunteerRecommendListResponse.getSprints() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> sprintSchools = volunteerRecommendListResponse.getSprints();
            for (int i = 0; i < Math.min(sprintLimit, sprintSchools.size()); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = sprintSchools.get(i);
                if (isSchoolMatch(schoolItem, school)) {
                    List<SchoolAnalysisRes.VolunteerInfo> schoolVolunteers = buildSchoolVolunteerInfoList(school, "冲");
                    if (schoolVolunteers != null && !schoolVolunteers.isEmpty()) {
                        volunteers.addAll(schoolVolunteers);
                        if (!shouldContinueByLevelForSchool(volunteers, "冲")) break;
                    }
                }
                if (!shouldContinueByLevelForSchool(volunteers, "冲")) break;
            }
        }

        // 在稳妥志愿中查找（只查找推荐范围内的）
        if (volunteerRecommendListResponse.getSafes() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> safeSchools = volunteerRecommendListResponse.getSafes();
            for (int i = 0; i < Math.min(safeLimit, safeSchools.size()); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = safeSchools.get(i);
                if (isSchoolMatch(schoolItem, school)) {
                    List<SchoolAnalysisRes.VolunteerInfo> schoolVolunteers = buildSchoolVolunteerInfoList(school, "稳");
                    if (schoolVolunteers != null && !schoolVolunteers.isEmpty()) {
                        volunteers.addAll(schoolVolunteers);
                        if (!shouldContinueByLevelForSchool(volunteers, "稳")) break;
                    }
                }
                if (!shouldContinueByLevelForSchool(volunteers, "稳")) break;
            }
        }

        // 在保底志愿中查找（只查找推荐范围内的）
        if (volunteerRecommendListResponse.getProtects() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> protectSchools = volunteerRecommendListResponse.getProtects();
            for (int i = 0; i < Math.min(protectLimit, protectSchools.size()); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = protectSchools.get(i);
                if (isSchoolMatch(schoolItem, school)) {
                    List<SchoolAnalysisRes.VolunteerInfo> schoolVolunteers = buildSchoolVolunteerInfoList(school, "保");
                    if (schoolVolunteers != null && !schoolVolunteers.isEmpty()) {
                        volunteers.addAll(schoolVolunteers);
                        if (!shouldContinueByLevelForSchool(volunteers, "保")) break;
                    }
                }
                if (!shouldContinueByLevelForSchool(volunteers, "保")) break;
            }
        }

        return volunteers;
    }

    /**
     * 在候补志愿中查找学校
     * 查找超出推荐范围的学校（候补学校）
     */
    private List<SchoolAnalysisRes.VolunteerInfo> findSchoolInCandidates(Long chatSessionId, SchoolAnalysisReq.SchoolItem schoolItem,
                                                                         VolunteerRecommendListResponse volunteerRecommendListResponse) {
        List<SchoolAnalysisRes.VolunteerInfo> candidates = Lists.newArrayList();

        // 获取推荐数量限制
        Map<String, Integer> targetCountMap = volunteerRecommendListResponse.getBaseData().getThree_target_count_map();
        int sprintLimit = targetCountMap.getOrDefault("sprints_count", 0);
        int safeLimit = targetCountMap.getOrDefault("safes_count", 0);
        int protectLimit = targetCountMap.getOrDefault("protects_count", 0);

        // 在冲刺志愿的候补部分中查找
        if (volunteerRecommendListResponse.getSprints() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> sprintSchools = volunteerRecommendListResponse.getSprints();
            for (int i = sprintLimit; i < sprintSchools.size(); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = sprintSchools.get(i);
                if (isSchoolMatch(schoolItem, school)) {
                    List<SchoolAnalysisRes.VolunteerInfo> schoolVolunteers = buildSchoolVolunteerInfoList(school, "冲");
                    if (schoolVolunteers != null && !schoolVolunteers.isEmpty()) {
                        candidates.addAll(schoolVolunteers);
                        if (!shouldContinueByLevelForSchool(candidates, "冲")) break;
                    }
                }
                if (!shouldContinueByLevelForSchool(candidates, "冲")) break;
            }
        }

        // 在稳妥志愿的候补部分中查找
        if (volunteerRecommendListResponse.getSafes() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> safeSchools = volunteerRecommendListResponse.getSafes();
            for (int i = safeLimit; i < safeSchools.size(); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = safeSchools.get(i);
                if (isSchoolMatch(schoolItem, school)) {
                    List<SchoolAnalysisRes.VolunteerInfo> schoolVolunteers = buildSchoolVolunteerInfoList(school, "稳");
                    if (schoolVolunteers != null && !schoolVolunteers.isEmpty()) {
                        candidates.addAll(schoolVolunteers);
                        if (!shouldContinueByLevelForSchool(candidates, "稳")) break;
                    }
                }
                if (!shouldContinueByLevelForSchool(candidates, "稳")) break;
            }
        }

        // 在保底志愿的候补部分中查找
        if (volunteerRecommendListResponse.getProtects() != null) {
            List<VolunteerRecommendListResponse.VolunteerSchool> protectSchools = volunteerRecommendListResponse.getProtects();
            for (int i = protectLimit; i < protectSchools.size(); i++) {
                VolunteerRecommendListResponse.VolunteerSchool school = protectSchools.get(i);
                if (isSchoolMatch(schoolItem, school)) {
                    List<SchoolAnalysisRes.VolunteerInfo> schoolVolunteers = buildSchoolVolunteerInfoList(school, "保");
                    if (schoolVolunteers != null && !schoolVolunteers.isEmpty()) {
                        candidates.addAll(schoolVolunteers);
                        if (!shouldContinueByLevelForSchool(candidates, "保")) break;
                    }
                }
                if (!shouldContinueByLevelForSchool(candidates, "保")) break;
            }
        }

        return candidates;
    }

    /**
     * 判断学校是否匹配
     */
    private boolean isSchoolMatch(SchoolAnalysisReq.SchoolItem schoolItem, VolunteerRecommendListResponse.VolunteerSchool school) {
        boolean isMatch = false;
        if (schoolItem.getName() != null && school.getSchool_name() != null) {
            isMatch = school.getSchool_name().contains(schoolItem.getName());
        }
        if (!isMatch) {
            isMatch = (schoolItem.getId() != null && schoolItem.getId().equals(school.getSchoolId()));
        }
        return isMatch;
    }


    /**
     * 构建学校志愿信息列表
     */
    private List<SchoolAnalysisRes.VolunteerInfo> buildSchoolVolunteerInfoList(VolunteerRecommendListResponse.VolunteerSchool school, String level) {
        List<SchoolAnalysisRes.VolunteerInfo> volunteers = Lists.newArrayList();

        if (school.getMajors() != null && !school.getMajors().isEmpty()) {
            SchoolAnalysisRes.VolunteerInfo volunteerInfo = new SchoolAnalysisRes.VolunteerInfo();
            volunteerInfo.setSchoolName(school.getSchool_name());
            volunteerInfo.setVolunteerLevel(level);
            volunteerInfo.setSchoolWeightInfo(school.getAlgTagMap());

            // 构建专业列表
            List<SchoolAnalysisRes.MajorInfo> majorList = Lists.newArrayList();
            for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                SchoolAnalysisRes.MajorInfo majorInfo = new SchoolAnalysisRes.MajorInfo();
                majorInfo.setMajorName(major.getMajor_name());
                majorInfo.setEnrollRate(major.getEnroll_ratio());
                majorInfo.setMajorWeightInfo(major.getAlgTagMap());
                majorList.add(majorInfo);
            }
            volunteerInfo.setMajorList(majorList);
            volunteers.add(volunteerInfo);
        }
        // 如果没有专业信息，返回空列表

        return volunteers;
    }

    /**
     * 生成推荐学校总结
     */
    private String generateSchoolRecommendSummary(String schoolName, List<SchoolAnalysisRes.VolunteerInfo> volunteers) {
        StringBuilder summary = new StringBuilder();
        summary.append("该学校在优选志愿中，为您推荐以下").append(volunteers.size()).append("个相关志愿：\n");

        for (SchoolAnalysisRes.VolunteerInfo volunteer : volunteers) {
            summary.append("• ").append(volunteer.getSchoolName()).append(" (")
                    .append(volunteer.getVolunteerLevel()).append("档)");

            if (volunteer.getMajorList() != null && !volunteer.getMajorList().isEmpty()) {
                summary.append(" 包含专业: ");
                for (int i = 0; i < volunteer.getMajorList().size(); i++) {
                    SchoolAnalysisRes.MajorInfo major = volunteer.getMajorList().get(i);
                    summary.append(major.getMajorName());
                    if (major.getEnrollRate() != null) {
                        summary.append("(录取率:").append(major.getEnrollRate()).append("%)");
                    }
                    if (i < volunteer.getMajorList().size() - 1) {
                        summary.append(", ");
                    }
                }
            }
            summary.append("\n");
        }

        return summary.toString();
    }

    /**
     * 生成候补学校分析
     */
    private String generateSchoolCandidateAnalysis(String schoolName, List<SchoolAnalysisRes.VolunteerInfo> volunteers) {
        StringBuilder summary = new StringBuilder();
        summary.append("在候补志愿列表中为您找到如下相关志愿：\n");

        // 显示候补志愿信息
        for (SchoolAnalysisRes.VolunteerInfo volunteer : volunteers) {
            summary.append("• ").append(volunteer.getSchoolName()).append(" (")
                    .append(volunteer.getVolunteerLevel()).append("档)");

            if (volunteer.getMajorList() != null && !volunteer.getMajorList().isEmpty()) {
                summary.append(" 包含专业: ");
                for (int i = 0; i < volunteer.getMajorList().size(); i++) {
                    SchoolAnalysisRes.MajorInfo major = volunteer.getMajorList().get(i);
                    summary.append(major.getMajorName());
                    if (major.getEnrollRate() != null) {
                        summary.append("(录取率:").append(major.getEnrollRate()).append("%)");
                    }
                    if (i < volunteer.getMajorList().size() - 1) {
                        summary.append(", ");
                    }
                }
            }
            summary.append("\n");
        }

        // 分析权重因素
        List<String> lowFactors = analyzeSchoolLowWeightFactors(volunteers);
        if (!lowFactors.isEmpty()) {
            summary.append("分析原因：该学校在以下维度权重较低：\n");
            for (String factor : lowFactors) {
                summary.append("• ").append(factor).append("\n");
            }
        } else {
            summary.append("分析原因：学校综合评分较低，地理位置、排名等因素影响匹配度。\n");
        }

        summary.append("建议：是否考虑将该学校加入院校意向来提高学校优先级。");

        return summary.toString();
    }

    /**
     * 分析学校权重较低的因素
     */
    private List<String> analyzeSchoolLowWeightFactors(List<SchoolAnalysisRes.VolunteerInfo> volunteers) {
        List<String> factors = Lists.newArrayList();

        for (SchoolAnalysisRes.VolunteerInfo volunteer : volunteers) {
            Object weightInfoObj = volunteer.getSchoolWeightInfo();
            if (weightInfoObj instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> weightInfo = (Map<String, Object>) weightInfoObj;

                // 检查省份GDP
                Object provinceGdp = weightInfo.get("province_gdp");
                if (provinceGdp instanceof Double && (Double) provinceGdp < 0.5) {
                    factors.add("所在省份经济发展水平较低");
                }

                // 检查城市等级
                Object cityLevel = weightInfo.get("city_level");
                if (cityLevel instanceof Double && (Double) cityLevel < 0.5) {
                    factors.add("所在城市等级较低");
                }

                // 检查考研率
                Object upgradeRatio = weightInfo.get("upgrade_ratio");
                if (upgradeRatio instanceof Double && (Double) upgradeRatio < 0.5) {
                    factors.add("考研率相对较低");
                }

                // 检查保研率
                Object recommendRatio = weightInfo.get("postgraduate_recommend_ratio");
                if (recommendRatio instanceof Double && (Double) recommendRatio < 0.5) {
                    factors.add("保研率相对较低");
                }

                // 检查学校排名
                Object gaotuRank = weightInfo.get("gaotu_rank");
                if (gaotuRank instanceof Double && (Double) gaotuRank < 0.5) {
                    factors.add("学校排名相对较低");
                }

                // 检查学校等级
                Object levelScore = weightInfo.get("level_score");
                if (levelScore instanceof Double && (Double) levelScore < 0.5) {
                    factors.add("学校等级相对较低");
                }

                // 检查学校综合得分
                Object collegeScore = weightInfo.get("college_score_new");
                if (collegeScore instanceof Double && (Double) collegeScore < 0.6) {
                    factors.add("学校综合得分较低");
                }
            }
        }

        return factors;
    }

    /**
     * 分析学校录取概率
     */
    private String analyzeSchoolAdmissionProbability(String schoolName, VolunteerRecommendListResponse volunteerRecommendListResponse) {
        StringBuilder summary = new StringBuilder();
        summary.append("结合该校往年分数，该学校不在您的分数的录取范围。");
        summary.append("建议：可以考虑其他更匹配的学校，或者调整分数期望。");

        return summary.toString();
    }

    /**
     * 查询专业、学校权重
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @param queryInfo     查询信息
     * @return 权重查询响应
     */
    public QueryWeightResponse queryWeight(Long tenantId, Long chatSessionId, QueryWeightDto queryInfo) {
        log.info("queryWeight: tenantId={}, chatSessionId={}, queryInfo={}", tenantId, chatSessionId, queryInfo);

        // 1. 获取用户数据
        CreateSessionReq userScoreDetail = dataProvider.getUserScoreDetail(chatSessionId);
        UserProfileData userProfileData = dataProvider.getUserProfileData(chatSessionId);

        // 2. 合并用户画像
        UserProfileData userFinalProfileData = utils.mergeUserProfile(userProfileData);
        log.info("queryWeight:userFinalProfileData:{}", userFinalProfileData);

        // 3. 构建请求参数
        QueryWeightRequest request = new QueryWeightRequest();
        request.setStudentinfo(userScoreDetail);
        request.setProfileinfo(userFinalProfileData);
        request.setQueryinfo(queryInfo);

        // 4. 调用权重查询接口
        return volunteerRankClient.queryWeight(request);
    }

}
