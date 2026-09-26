package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CandidateItemDTO {
    private String volunteerId;
    private String tier;
    private String subTier;
    private String planSchoolDataId;
    private String schoolId;
    private String schoolUnitCode;
    private String schoolName;
    private String displaySchoolName;
    private String provinceName;
    private String cityName;
    // 区域 ID（来自志愿文件的 `area.key` / `city.key` ✓）。
    // 有 ID 才能"按 ID 相等"判同一个地区 ✓；没有时仍旧按规范化名字兜底 ✓。
    private String provinceId;
    private String cityId;
    private String schoolBatch;
    private String schoolLevel;
    private String schoolNature;
    private String schoolCategory;
    private Integer schoolRank;
    private Double schoolEnrollRatio;
    private Double baoyanRatio;
    private Double upgradeRatio;
    private Integer masterCount;
    private Integer doctorCount;
    private Boolean preferred;
    private String majorId;
    private String majorName;
    private String majorCode;
    private String majorCategoryId;
    private String majorSubCategoryId;
    private String majorLevel;
    private String majorDiscipline;
    private String majorCategory;
    private String majorTier;
    private Integer planNum;
    private String duration;
    private Integer tuitionPerYear;
    private Double baseScore;
    private Double intentScore;
    private Double finalScore;
    private Double futureDevelopmentScore;
    private Double admissionRatio;
    private Integer rankInTier;
    private Double hotIndex;
    private Double salaryAvg;
    private List<String> mustSubjects = Lists.newArrayList();
    private List<String> reasonCodes = Lists.newArrayList();
    private List<String> riskFlags = Lists.newArrayList();
    private List<String> schoolRankTags = Lists.newArrayList();
    private List<String> schoolBasicTags = Lists.newArrayList();
    private List<String> schoolPopupTags = Lists.newArrayList();
    private List<String> majorRankTags = Lists.newArrayList();
    private List<String> majorPlanTags = Lists.newArrayList();
    private List<HistoryScoreItem> schoolHistoryScores = Lists.newArrayList();
    private List<HistoryScoreItem> majorHistoryScores = Lists.newArrayList();

    @Data
    public static class HistoryScoreItem {
        private Integer year;
        private Integer score;
        private Integer pos;
        private Integer planNum;
        private Integer enrollNum;
    }
}
