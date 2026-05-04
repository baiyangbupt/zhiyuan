package com.ytell.zhiyuan.model.dto;

import com.ytell.zhiyuan.model.enums.TargetType;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
public class CreateSessionReq {

    private Long botId;//
    private String userName; // 用户姓名

    private Province province; // 高考省份
    private Integer examYear; // 高考年份
    private Sex sex; // 性别
    private List<SubjectItem> subjectList; // 科目列表

    private SubjectType subjectType; // 科目类型
    private PrepareType prepareType;//填报类型

    private String filterType="2";//# 1:专业不限 2:非负向专业 3:正向专业

    //
    private Boolean specialPlan; // 是否有专项计划
    private Boolean minority; // 是否少数民族
    private Boolean colorBlindness; // 是否色盲色弱
    private Boolean bonusPolicy; // 是否有加分政策
    private Integer bonusScore; // 加分
    private Integer totalScore; // 总分
    private Batch batch; // 批次
    private List<SubjectScore> subjectScoreList; // 科目分数列表
    private TargetType targetType; // 目标类型：学校优先、专业优先、城市优先

    //调用接口
    private VolunteerCount volunteerCount; //所在省份填报所需志愿数

    /// 🔧总得分位次
    private Integer totalScorePos;

    //🔧 填报类型：粗分：major=专业+院校，majorGroup=专业组
    private VolunteerModel volunteerModel;
    //🔧//填报类型：细分
    private String volunteerDetailModel;

    //🔧 优势学科
    private List<SubjectScore> strengthSubjectList;

    // 🔧 身高信息
    private String height;

    // 🔧 色觉情况
    private List<String> colorSistuation;

    // 🔧 视力情况
    private VisionAbility visionAbility;

    // 🔧 民族信息
    private Ethnicity ethnicity;

    // 🔧 政治面貌
    private PoliticalStatus politicalStatus;

    // 🔧 意向专业 - 二级专业分类
    private List<PreferredMajor> preferredMajors;

    // 🔧 不能接受的专业 - 三级专业
    private List<UnacceptableMajor> unacceptableMajors;

    // 🔧 是否接受中外合作专业
    private Boolean acceptForeignSchool;

    // 🔧 地区偏好 - 省份列表
    private List<PreferredRegion> preferredRegions;

    // 🔧 志愿填报策略
    private StrategyType strategyType;

    // 🔧 学费范围
    private TuitionRange tuitionRange;

    @Data
    public static class Province {
        private String code;
        private String name;
    }

    @Data
    public static class Sex {
        private String code; // male、female
        private String name;
    }

    @Data
    public static class SubjectType {
        private String code; // WL、LS、N
        private String desc; // 物理、历史、综合
    }

    @Data
    public static class PrepareType {
        private String code; //VOLUNTEER
        private String desc; // 智能填报、模拟填报
    }


    @Data
    @AllArgsConstructor
    @NoArgsConstructor
    public static class SubjectItem {
        private Integer isFirst;
        private String subjectType;
        private String value;
        private String name;
    }

    @Data
    public static class Batch {
        private String code;
        private String name;
        private Float score;
        private String level;
        private Integer pos;
    }

    @Data
    public static class ExamType {
        private String code;
        private String desc;
    }

    @Data
    public static class SubjectScore {
        private String subject;
        private String subjectName;
        private Integer score;
    }

    @Data
    public static class VolunteerCount {
        private Integer schoolCount;
        private Integer majorCount;
    }

    @Data
    public static class VisionAbility {
        private String left;
        private String right;
    }

    @Data
    public static class Ethnicity {
        private String code;
        private String name;
    }

    @Data
    public static class PoliticalStatus {
        private String code;
        private String name;
    }

    @Data
    public static class PreferredMajor {
        private String majorSubId;
        private String majorSubName;
    }

    @Data
    public static class UnacceptableMajor {
        private String majorId;
        private String majorName;
    }

    @Data
    public static class PreferredRegion {
        private String provinceId;
        private String provinceName;
    }

    @Data
    public static class StrategyType {
        private String code;
        private String name;
    }

    @Data
    @AllArgsConstructor
    @NoArgsConstructor
    public static class TuitionRange {
        private Integer min;
        private Integer max;
    }

}
