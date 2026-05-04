package com.ytell.zhiyuan.service.volunteer;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.gaotu.MemberScoreDetailDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;

/**
 * 优势学科计算服务
 * 根据用户分数信息计算优势学科排序
 */
@Slf4j
@Service
public class AdvantageSubjectService {

    /**
     * 一般省市(包含海南除上海), 语数外150满分, 政史地100满分
     */
    private static final Map<String, Double> ORDINARY_FULL_MARKS = new HashMap<String, Double>() {{
        put("语文", 150.0);
        put("数学", 150.0);
        put("英语", 150.0);
        put("物理", 100.0);
        put("化学", 100.0);
        put("生物", 100.0);
        put("政治", 100.0);
        put("历史", 100.0);
        put("地理", 100.0);
    }};

    /**
     * 上海市选科都是70分满分
     */
    private static final Map<String, Double> SHANGHAI_FULL_MARKS = new HashMap<String, Double>() {{
        put("语文", 150.0);
        put("数学", 150.0);
        put("英语", 150.0);
        put("物理", 70.0);
        put("化学", 70.0);
        put("生物", 70.0);
        put("政治", 70.0);
        put("历史", 70.0);
        put("地理", 70.0);
    }};

    /**
     * 根据用户分数信息计算优势学科排序
     *
     * @param userScoreInfo 用户分数信息
     * @return 按分数比率降序排列的学科列表，如果数据不完整则返回默认值
     */
    public List<SubjectScoreRatio> getSortedUserCompetence(MemberScoreDetailDTO userScoreInfo) {
        if (userScoreInfo == null) {
            log.error("用户分数信息为空");
            return getDefaultSubjectList();
        }

        if (userScoreInfo.getAreaName() == null) {
            log.error("areaName not found in userScoreInfo.");
            return getDefaultSubjectList();
        }

        // 根据地区确定满分标准
        Map<String, Double> fullMark;
        if ("上海".equals(userScoreInfo.getAreaName())) {
            fullMark = SHANGHAI_FULL_MARKS;
        } else {
            fullMark = ORDINARY_FULL_MARKS;
        }

        // 获取用户的科目分数列表
        try {
            List<MemberScoreDetailDTO.MemberSubject> subjectList = userScoreInfo.getMemberSubjectList();
            if (subjectList == null || subjectList.isEmpty()) {
                log.warn("memberSubjectList为空，返回默认优势学科");
                return getDefaultSubjectList();
            }

            // 计算分数比率
            List<SubjectScoreRatio> subjectScoreRatioList = new ArrayList<>();
            for (MemberScoreDetailDTO.MemberSubject subject : subjectList) {
                if (subject.getSubject() != null && subject.getScore() != null) {
                    String subjectName = subject.getSubject().getData();
                    Double fullScore = fullMark.get(subjectName);

                    if (fullScore != null) {
                        try {
                            Double score = Double.parseDouble(subject.getScore());
                            Double ratio = score / fullScore;
                            subjectScoreRatioList.add(new SubjectScoreRatio(subjectName, ratio));
                        } catch (NumberFormatException e) {
                            log.warn("分数格式错误: subject={}, score={}", subjectName, subject.getScore());
                        }
                    } else {
                        log.warn("未找到学科满分标准: {}", subjectName);
                    }
                }
            }

            if (subjectScoreRatioList.isEmpty()) {
                log.warn("无法计算任何学科分数比率，返回默认优势学科");
                return getDefaultSubjectList();
            }

            // 按照分数比率降序排列
            return subjectScoreRatioList.stream()
                    .sorted((a, b) -> Double.compare(b.getRatio(), a.getRatio()))
                    .collect(Collectors.toList());

        } catch (Exception e) {
            // user score info 不完整(调试期间), 回退到数学和语文默认优势学科
            log.warn("Invalid score info: {}", e.getMessage());
            return getDefaultSubjectList();
        }
    }

    /**
     * 根据CreateSessionReq计算优势学科排序
     *
     * @param createSessionReq 创建会话请求
     * @return 按分数比率降序排列的学科列表
     */
    public List<SubjectScoreRatio> getSortedUserCompetence(CreateSessionReq createSessionReq) {
        // 根据地区确定满分标准
        Map<String, Double> fullMark;
        if ("上海".equals(createSessionReq.getProvince().getName())) {
            fullMark = SHANGHAI_FULL_MARKS;
        } else {
            fullMark = ORDINARY_FULL_MARKS;
        }

        // 获取用户的科目分数列表
        try {
            List<CreateSessionReq.SubjectScore> subjectScoreList = createSessionReq.getSubjectScoreList();
            if (subjectScoreList == null || subjectScoreList.isEmpty()) {
                log.warn("学科分数列表为空，返回默认优势学科");
                return getDefaultSubjectList();
            }

            // 计算分数比率
            List<SubjectScoreRatio> subjectScoreRatioList = new ArrayList<>();
            for (CreateSessionReq.SubjectScore subjectScore : subjectScoreList) {
                if (subjectScore.getSubjectName() != null && subjectScore.getScore() != null) {
                    String subjectName = subjectScore.getSubjectName();
                    Double fullScore = fullMark.get(subjectName);

                    if (fullScore != null) {
                        Double ratio = (double) subjectScore.getScore() / fullScore;
                        subjectScoreRatioList.add(new SubjectScoreRatio(subjectName, ratio));
                    } else {
                        log.warn("未找到学科满分标准: {}", subjectName);
                    }
                }
            }

            if (subjectScoreRatioList.isEmpty()) {
                log.warn("无法计算任何学科分数比率，返回默认优势学科");
                return getDefaultSubjectList();
            }

            // 按照分数比率降序排列
            return subjectScoreRatioList.stream()
                    .sorted((a, b) -> Double.compare(b.getRatio(), a.getRatio()))
                    .collect(Collectors.toList());

        } catch (Exception e) {
            log.warn("计算优势学科时发生错误: {}", e.getMessage());
            return getDefaultSubjectList();
        }
    }

    /**
     * 获取前两个优势学科名称列表
     *
     * @param createSessionReq 创建会话请求
     * @return 前两个优势学科名称列表
     */
    public List<String> getTopTwoSubjectList(CreateSessionReq createSessionReq) {
        List<SubjectScoreRatio> sortedSubjects = getSortedUserCompetence(createSessionReq);
        return sortedSubjects.stream()
                .limit(2)
                .map(SubjectScoreRatio::getSubjectName)
                .collect(Collectors.toList());
    }

    /**
     * 获取默认优势学科列表（数学和语文）
     *
     * @return 默认优势学科列表
     */
    private List<SubjectScoreRatio> getDefaultSubjectList() {
        return Arrays.asList(
                new SubjectScoreRatio("数学", 0.5),
                new SubjectScoreRatio("语文", 0.5)
        );
    }

    /**
     * 获取学科满分标准
     *
     * @param areaName 地区名称
     * @return 学科满分标准Map
     */
    public Map<String, Double> getFullMarkStandard(String areaName) {
        if ("上海".equals(areaName)) {
            return new HashMap<>(SHANGHAI_FULL_MARKS);
        } else {
            return new HashMap<>(ORDINARY_FULL_MARKS);
        }
    }

    /**
     * 学科分数比例结果类
     */
    public static class SubjectScoreRatio {
        private String subjectName;
        private Double ratio;

        public SubjectScoreRatio(String subjectName, Double ratio) {
            this.subjectName = subjectName;
            this.ratio = ratio;
        }

        public String getSubjectName() {
            return subjectName;
        }

        public Double getRatio() {
            return ratio;
        }

        @Override
        public String toString() {
            return "SubjectScoreRatio{" +
                    "subjectName='" + subjectName + '\'' +
                    ", ratio=" + ratio +
                    '}';
        }
    }
}
