package com.ytell.zhiyuan.model.dto.inner;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class SchoolMajorBean {
    // 学校相关
    private String schoolId; // 学校ID
    @JsonProperty("school_name")
    private String schoolName; // 学校名称
    @JsonProperty("school_volunteer_level")
    private String schoolVolunteerLevel; // 学校冲稳保（SPRINT、SAFE、PROTECT）
    @JsonProperty("school_enroll_ratio")
    private Double schoolEnrollRatio; // 学校录取率
    private String city; // 城市
    private List<String> district; // 区域
    @JsonProperty("authority")
    private List<String> authority; // 主管部门
    @JsonProperty("historic_authorities")
    private List<String> historicAuthorities; // 历史沿革
    @JsonProperty("legacy_honor")
    private List<String> legacyHonor; // 历史荣誉
    private List<String> level; // 学校层次
    private List<String> nature; // 学校性质
    @JsonProperty("school_category")
    private List<String> schoolCategory;//学校类别
    @JsonProperty("postgraduate")
    private Boolean postgraduate; // 是否有研究生教育
    @JsonProperty("double_first_major")
    private Boolean doubleFirstMajor; // 是否有双一流专业
    @JsonProperty("goat_major")
    private List<String> goatMajor; // 优势专业
    @JsonProperty("fourth_evaluate_roll")
    private List<String> fourthEvaluateRoll; // 第四轮学科评估结果
    @JsonProperty("legacy_strong_side")
    private List<String> legacyStrongSide; // 传统优势方向
    @JsonProperty("legacy_strong_major")
    private List<String> legacyStrongMajor; // 传统优势专业
    @JsonProperty("district_flourishing_industry")
    private List<String> districtFlourishingIndustry; // 区域支柱产业
    @JsonProperty("city_flourishing_industry")
    private List<String> cityFlourishingIndustry; // 城市支柱产业
    @JsonProperty("recruitment_policy")
    private List<String> recruitmentPolicy; // 招生政策

    // 专业相关
    private String majorId; // 专业ID
    @JsonProperty("major_name")
    private String majorName; // 专业名称
    @JsonProperty("category")
    private List<String> category; // 一级类目
    @JsonProperty("sub_category")
    private List<String> subCategory; // 二级类目
    @JsonProperty("major_volunteer_level")
    private String majorVolunteerLevel; // 专业冲稳保（SPRINT、SAFE、PROTECT）
    @JsonProperty("major_enroll_ratio")
    private Double majorEnrollRatio; // 专业录取率
    @JsonProperty("select_info")
    private List<String> selectInfo; // 选考信息
    @JsonProperty("subject_tendency")
    private List<String> subjectTendency; // 学科倾向
    @JsonProperty("subject_division_tendency")
    private List<String> subjectDivisionTendency; // 学科分科倾向
    @JsonProperty("interest_tendency")
    private List<String> interestTendency; // 兴趣倾向
    @JsonProperty("gender_tendency")
    private List<String> genderTendency; // 性别倾向
    @JsonProperty("personality_tendency")
    private List<String> personalityTendency; // 性格倾向
    @JsonProperty("graduate_tendency")
    private List<String> graduateTendency; // 毕业倾向
    @JsonProperty("profession_tendency")
    private List<String> professionTendency; // 职业倾向
    @JsonProperty("industry_tendency")
    private List<String> industryTendency; // 行业倾向
    @JsonProperty("work_unit_tendency")
    private List<String> workUnitTendency; // 工作单位倾向
    @JsonProperty("work_style_tendency")
    private List<String> workStyleTendency; // 工作风格倾向
    @JsonProperty("pivot_school")
    private List<String> pivotSchool; // 主流院校
}