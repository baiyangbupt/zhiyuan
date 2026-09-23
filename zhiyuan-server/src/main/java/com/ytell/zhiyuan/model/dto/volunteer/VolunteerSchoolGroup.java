package com.ytell.zhiyuan.model.dto.volunteer;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 统一的院校专业组数据结构
 * 专业+院校模式：majorList只有一条记录
 * 院校专业组模式：majorList有多条记录
 */
@Data
public class VolunteerSchoolGroup {
    // 院校信息（以planSchoolDataId作为唯一标识）
    private String planSchoolDataId;      // 院校招生计划ID（唯一标识）
    private String schoolId;              // 院校ID
    private String schoolName;            // 院校名称
    private String schoolUnitCode;        // 院校代码

    // 院校录取信息（用于区间划分）
    private Double schoolEnrollRatio;     // 院校录取率（数值）
    private String schoolEnrollRatioStr;  // 院校录取率（字符串）
    private String schoolVolunteerLevel;  // 院校冲稳保等级

    // 院校排名信息
    private Integer schoolRank;           // 院校排名

    // 院校地理位置信息
    private String provinceName;              // 院校省份
    private String cityName;                  // 院校城市
    private String provinceId;            // 院校省份ID
    private String cityId;                // 院校城市ID
    // 学校历史录取数据（使用简化的数据结构）
    private List<HistoryRecordDTO> historyRecords;

    // 专业列表
    private List<VolunteerMajor> majorList;

    // 院校评估指标
    private Double province_gdp;                    // 省份GDP指数
    private Integer city_level;                     // 城市等级指数
    private Double upgrade_ratio;                   // 考研率指数
    private Double postgraduate_recommend_ratio;    // 保研率指数
    private Double gaotu_rank;                      // 院校排名指数
    private Integer level_score;                    // 院校等级指数
    private Double college_score_old;               // 院校原始得分
    private Double college_score_new;               // 院校最终得分
    private String college_remark;                  // 院校得分调整说明
    /**
     * 院校侧逐因子增量，来自 rank（P1d）。**逐行原样透传**，语义由
     * {@code RankReasonMapper} 负责收口——这一层不放中文标签之外的判断。
     */
    private List<Map<String, Object>> college_factors;
    /**
     * 院校侧的结构化理由（Java 映射出来的稳定 code/name/weight/delta/reason）。
     * 与 {@link #college_remark} **并存**：那串是既有前端/导出在用的旧通道。
     */
    private List<RankReasonDTO> collegeReasons;
    /** 专业侧逐因子增量，来自 rank（P1d）。 */
    private List<Map<String, Object>> major_factors;
    /** 专业侧的结构化理由（见 {@link #collegeReasons}）。 */
    private List<RankReasonDTO> majorReasons;
    private Double volunteer_score;                 // 志愿得分
    private Double major_score;   // 专业（类）得分

}

