package com.ytell.zhiyuan.model.dto.inner;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.enums.TargetType;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
@ApiModel("志愿推荐列表响应")
public class VolunteerRecommendListResponse {

    @ApiModelProperty("基础数据-用户分数信息")
    private CreateSessionReq userScoreDetail;
    @ApiModelProperty("基础数据-用户画像")
    private UserProfileData userFinalProfileData;

    @ApiModelProperty("基础数据")
    private BaseData baseData;

    @ApiModelProperty("冲刺志愿列表")
    private List<VolunteerSchool> sprints;

    @ApiModelProperty("稳妥志愿列表")
    private List<VolunteerSchool> safes;

    @ApiModelProperty("保底志愿列表")
    private List<VolunteerSchool> protects;
    @ApiModelProperty("是否是专业+院校模式")
    private Boolean majorSchoolType;

    @Data
    @ApiModel("基础数据")
    public static class BaseData {
        @ApiModelProperty("目标类型")
        private TargetType target_type;

        @ApiModelProperty("总志愿数")
        private Integer total_count;

        @ApiModelProperty("目标志愿数")
        private Integer need_count;

        @ApiModelProperty("冲刺志愿录取率范围")
        private List<String> sprints_enroll_ratio;

        @ApiModelProperty("稳妥志愿录取率范围")
        private List<String> safes_enroll_ratio;

        @ApiModelProperty("保底志愿录取率范围")
        private List<String> protects_enroll_ratio;

        @ApiModelProperty("冲志愿数")
        private Integer sprints_count;
        @ApiModelProperty("稳志愿数")
        private Integer safes_count;
        @ApiModelProperty("保志愿数")
        private Integer protects_count;
        @ApiModelProperty("冲稳保目标志愿数")
        private  Map<String, Integer> three_target_count_map;
        @ApiModelProperty("志愿表名")
        private String reportName;
        @ApiModelProperty("用户基本信息总结")
        private String userInfoSummary;
        @ApiModelProperty("最终志愿数量要求")
        private CreateSessionReq.VolunteerCount volunteerCount; //所在省份填报所需志愿数

        //填报类型：粗分：major=专业+院校，majorGroup=专业组
        @ApiModelProperty("填报模式")
        private VolunteerModel volunteerModel;

        @ApiModelProperty("当前会话生效中的学费区间")
        private CreateSessionReq.TuitionRange tuitionRange;

        @ApiModelProperty("学费区间配置：允许调节的总范围与步长")
        private TuitionRangeConfig tuitionRangeConfig;

        @ApiModelProperty("填报类型")
        private CreateSessionReq.PrepareType prepareType;

    }

    @Data
    @ApiModel("学费区间配置")
    public static class TuitionRangeConfig {

        @ApiModelProperty("最小学费（元/年）")
        private Integer min;

        @ApiModelProperty("最大学费（元/年）")
        private Integer max;

        @ApiModelProperty("步长（元），可选")
        private Integer step;

    }

    @Data
    @ApiModel("志愿学校信息")
    public static class VolunteerSchool {
        @ApiModelProperty("院校招生计划ID（唯一标识）")
        private String planSchoolDataId;
        @ApiModelProperty("院校ID")
        private String schoolId;
        @ApiModelProperty("院校代码")
        private String schoolUnitCode;
        @ApiModelProperty("学校名称")
        private String school_name;
        @ApiModelProperty("学校所在省份")
        private String province_name;
        @ApiModelProperty("学校所在城市")
        private String city_name;
        @ApiModelProperty("办学层次")
        private String school_batch;
        @ApiModelProperty("办学等级")
        private String school_level;
        @ApiModelProperty("办学性质")
        private String school_nature;
        @ApiModelProperty("学校类别")
        private String school_category;

       // 学校荣誉
        @ApiModelProperty("院校排名")
        private Integer school_rank;
        @ApiModelProperty("保研率")
        private Double baoyan_ratio;
        @ApiModelProperty("升学率")
        private Double upgrade_ratio;
        @ApiModelProperty("硕士点数量")
        private Integer master_count;
        @ApiModelProperty("博士点数量")
        private Integer doctor_count;

        //志愿情况
        @ApiModelProperty("志愿等级")
        private String level;
        @ApiModelProperty("录取率")
        private String enroll_ratio;
        @ApiModelProperty("历史分数列表")
        private List<HistoryScore> history_score_list= Lists.newArrayList();

        //专业情况
        @ApiModelProperty("专业列表")
        private List<VolunteerMajor> majors;

        //标签
        @ApiModelProperty("学校排序标签")
        private List<String> rankTagList= Lists.newArrayList();
        @ApiModelProperty("学校基础标签")
        private List<String> basicTagList= Lists.newArrayList();
        @ApiModelProperty("学校信息弹窗标签")
        private List<String> popTagList= Lists.newArrayList();
        @ApiModelProperty("学校算法标签")
        private Map<String, Object> algTagMap = Maps.newHashMap();

        @ApiModelProperty("层级内排名（按volunteer_score降序，1=最推荐）")
        private Integer rank_in_tier;
        @ApiModelProperty("是否为系统优选志愿")
        private Boolean is_preferred;

    }

    @Data
    @ApiModel("历史分数")
    public static class HistoryScore {
        @ApiModelProperty("年份")
        private Integer year;
        @ApiModelProperty("分数")
        private Integer score;
        @ApiModelProperty("位次")
        private Integer pos;
        @ApiModelProperty("计划数量")
        private Integer planNum;
        @ApiModelProperty("录取数量")
        private Integer enrollNum;
    }

    @Data
    @ApiModel("志愿专业信息")
    public static class VolunteerMajor {
        @ApiModelProperty("专业招生计划ID")
        private String planMajorDataId;
        @ApiModelProperty("专业名称")
        private String major_name;
        @ApiModelProperty("专业代码")
        private String majorUnitCode;
        @ApiModelProperty("专业ID")
        private String majorId;
        @ApiModelProperty("专业类别ID")
        private String categoryId;
        @ApiModelProperty("专业子类别ID")
        private String subCategoryId;
        @ApiModelProperty("录取率")
        private String enroll_ratio;
        @ApiModelProperty("志愿等级")
        private String level;
        @ApiModelProperty("计划数")
        private Integer planNum;
        @ApiModelProperty("专业费用")
        private String planMoney;
        @ApiModelProperty("专业学制")
        private String duration;
        @ApiModelProperty("必选科目")
        private List<String> must_subject;
        @ApiModelProperty("历史分数列表")
        private List<HistoryScore> history_score_list= Lists.newArrayList();
        @ApiModelProperty("专业排序标签")
        private List<String> rankTagList= Lists.newArrayList();
        @ApiModelProperty("专业计划标签")
        private List<String> planTagList= Lists.newArrayList();
        @ApiModelProperty("专业算法标签")
        private Map<String, Object> algTagMap = Maps.newHashMap();

    }
}
