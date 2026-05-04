package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@ApiModel("获取方案列表响应")
public class ProgramPageDTO {
    @ApiModelProperty("方案模型")
    private ProgramModel model;

    @ApiModelProperty("方案详细内容")
    private List<SchoolDetail> detailList;

    @ApiModelProperty("数据类型")
    private Type type;

    @ApiModelProperty("选科策略，01-老高考文理，02-3+1+2，03-N选3")
    private String policy;

    @ApiModelProperty("方案策略是否为最新策略")
    private Boolean isLatestPolicy;

    @ApiModelProperty("数据展示类型")
    private KeyData modeEnum;

    @Data
    public static class ProgramModel {
        @ApiModelProperty("当前方案使用的填报策略ID")
        private String volunteerPolicyId;

        @ApiModelProperty("方案批次")
        private KeyData batch;

        @ApiModelProperty("方案中的分数")
        private String score;

        @ApiModelProperty("方案中的位次")
        private Integer pos;

        @ApiModelProperty("方案中的选科类型")
        private Type subjectType;

        @ApiModelProperty("方案类型，PREDICT-模拟填报，VOLUNTEER-志愿填报")
        private Type type;

        @ApiModelProperty("方案中院校总数")
        private Integer schoolTotalNum;

        @ApiModelProperty("方案中\"冲\"的院校总数")
        private Integer schoolSprintNum;

        @ApiModelProperty("方案中\"稳\"的院校总数")
        private Integer schoolSafeNum;

        @ApiModelProperty("方案中\"保\"的院校总数")
        private Integer schoolProtectNum;

        @ApiModelProperty("方案中\"垫\"的院校总数，当前系统已去除垫的概念，可忽略")
        private Integer schoolInsuranceNum;

        @ApiModelProperty("方案中专业总数")
        private Integer majorTotalNum;

        @ApiModelProperty("方案中\"冲\"的专业总数")
        private Integer majorSprintNum;

        @ApiModelProperty("方案中\"稳\"的专业总数")
        private Integer majorSafeNum;

        @ApiModelProperty("方案中\"保\"的专业总数")
        private Integer majorProtectNum;

        @ApiModelProperty("方案中\"垫\"的专业总数，当前系统已去除垫的概念，可忽略")
        private Integer majorInsuranceNum;

        @ApiModelProperty("方案中的省份")
        private KeyData area;

        @ApiModelProperty("方案中的具体选科")
        private List<SubjectInfo> subjectList;

        @ApiModelProperty("方案选科文字展示")
        private String subjectSimpleStr;
    }

    @Data
    public static class SchoolDetail {
        @ApiModelProperty("院校ID")
        private String schoolId;

        @ApiModelProperty("院校招生数据ID，保存方案时前端需要传参")
        private String planSchoolDataId;

        @ApiModelProperty("数据类型，SPRINT-冲，SAFE-稳，PROTECT-保")
        private Type volunteerLevel;

        @ApiModelProperty("录取概率")
        private String enrollRatio;

        @ApiModelProperty("填报建议")
        private String enrollAdvice;

        @ApiModelProperty("招生单位名称")
        private String schoolUnitName;

        @ApiModelProperty("招生单位代码")
        private String schoolUnitCode;

        @ApiModelProperty("院校标签code列表")
        private String tag;

        @ApiModelProperty("院校标签列表")
        private List<String> tagList;

        @ApiModelProperty("院校分类")
        private List<String> classifyList;

        @ApiModelProperty("院校地址")
        private String address;

        @ApiModelProperty("省份信息")
        private KeyData area;

        @ApiModelProperty("城市信息")
        private KeyData city;

        @ApiModelProperty("院校类型")
        private KeyData type;

        @ApiModelProperty("专业数")
        private Integer majorCount;

        @ApiModelProperty("是否为新增院校")
        private Boolean schoolIsNew;

        @ApiModelProperty("院校层级")
        private Type level;

        @ApiModelProperty("院校位次")
        private Long schoolPos;

        @ApiModelProperty("院校分数")
        private String schoolScore;

        @ApiModelProperty("院校计划数量")
        private Integer planNum;

        @ApiModelProperty("院校转换过程")
        private String converProcess;

        @ApiModelProperty("增加数量")
        private Integer increaseNum;

        @ApiModelProperty("校友会排名")
        private Integer xyhRank;

        @ApiModelProperty("是否选择学校")
        private Boolean selectSchool;

        @ApiModelProperty("院校主管部门")
        private String authorities;

        @ApiModelProperty("录取规则")
        private String rule;

        @ApiModelProperty("选科信息")
        private String selectInfo;

        @ApiModelProperty("限报要求列表")
        private List<String> registrationConditionList;

        @ApiModelProperty("历史录取数据")
        private List<SubVO> subVOList;

        @ApiModelProperty("专业列表")
        private List<MajorVO> majorVOList;

        //特殊情况。
        //当type为OTOO/ OTOOWL的时候 majorId、majorUnitName等在外面，不在majorVOList里
        @ApiModelProperty("专业Id")
        private String majorId;
        @ApiModelProperty("专业名称")
        private String majorUnitName;

        @ApiModelProperty("是否新增专业")
        private Boolean majorIsNew;
        @ApiModelProperty("专业位次")
        private Long majorPos;
        @ApiModelProperty("专业分数")
        private String majorScore;
        @ApiModelProperty("专业code")
        private String majorUnitCode;
        @ApiModelProperty("专业招生计划ID")
        private String planMajorDataId;
        @ApiModelProperty("专业费用")
        private String planMoney;

        @ApiModelProperty("专业学制")
        private String planDuration;
        @ApiModelProperty("是否双一流专业")
        private Boolean isDoubleFirstMajor;
        @ApiModelProperty("专业一级类目id")
        private String categoryId;
        @ApiModelProperty("专业二级类目id")
        private String subCategoryId;

    }

    @Data
    public static class MajorVO {
        @ApiModelProperty("院校招生计划ID")
        private String planSchoolDataId;

        @ApiModelProperty("专业招生计划ID")
        private String planMajorDataId;

        @ApiModelProperty("数据类型，SPRINT-冲，SAFE-稳，PROTECT-保")
        private Type volunteerLevel;

        @ApiModelProperty("录取概率")
        private String enrollRatio;

        @ApiModelProperty("填报建议")
        private String enrollAdvice;

        @ApiModelProperty("专业ID")
        private String majorId;


        @ApiModelProperty("专业计划数量")
        private Integer planNum;
        @ApiModelProperty("专业分数")
        private Integer score;
        @ApiModelProperty("专业code")
        private String unitCode;

        @ApiModelProperty("专业位次")
        private Long pos;

        @ApiModelProperty("专业一级类目id")
        private String categoryId;
        @ApiModelProperty("专业二级类目id")
        private String subCategoryId;
        @ApiModelProperty("专业选科")
        private String selectInfo;
        @ApiModelProperty("专业费用")
        private String money;
        @ApiModelProperty("招生单位名称")
        private String unitName;

        @ApiModelProperty("是否新增专业")
        private Boolean isNew;

        @ApiModelProperty("专业名称")
        private String majorName;

        @ApiModelProperty("是否双一流专业")
        private Boolean isDoubleFirstMajor;

        @ApiModelProperty("招生单位代码")
        private String schoolUnitCode;

        @ApiModelProperty("增加数量")
        private Integer increaseNum;

        @ApiModelProperty("专业学制")
        private String duration;

        @ApiModelProperty("专业转换过程")
        private String converProcess;

        @ApiModelProperty("学校ID")
        private String schoolId;

        @ApiModelProperty("高亮标志")
        private Integer highLightFlag;

        @ApiModelProperty("是否选择专业")
        private Boolean selectZy;

        @ApiModelProperty("限报要求列表")
        private List<String> registrationConditionList;

        @ApiModelProperty("专业评估等级")
        private String evaluateRollForth;

        @ApiModelProperty("历史录取数据")
        private List<SubVO> subVOList;
    }


    @Data
    @AllArgsConstructor
    @NoArgsConstructor
    public static class Type {
        @ApiModelProperty("代码")
        private String code;

        @ApiModelProperty("描述")
        private String desc;
    }

    @Data
    public static class SubVO {
        @ApiModelProperty("平均录取分数")
        private String enrollAvgScoreDb;

        @ApiModelProperty("文科录取分数")
        private String wEnrollScoreDb;

        @ApiModelProperty("理科录取位次")
        private String lEnrollPos;

        @ApiModelProperty("年份")
        private String year;

        @ApiModelProperty("录取专业ID")
        private String enrollMajorId;

        @ApiModelProperty("录取分数")
        private String enrollScoreDb;

        @ApiModelProperty("计划数量")
        private String planNum;

        @ApiModelProperty("增加数量")
        private Integer increaseNum;

        @ApiModelProperty("是否文理")
        private Boolean wl;

        @ApiModelProperty("录取数量")
        private String enrollNum;

        @ApiModelProperty("文科计划数量")
        private String wPlanNum;

        @ApiModelProperty("文科平均录取位次")
        private String wEnrollAvgPos;

        @ApiModelProperty("理科计划数量")
        private String lPlanNum;

        @ApiModelProperty("录取专业副标题")
        private String enrollMajorSubtitle;

        @ApiModelProperty("平均录取分数")
        private String enrollAvgScore;

        @ApiModelProperty("文科录取分数")
        private String wEnrollScore;

        @ApiModelProperty("录取位次")
        private String enrollPos;

        @ApiModelProperty("录取分数")
        private String enrollScore;

        @ApiModelProperty("平均录取位次")
        private String enrollAvgPos;

        @ApiModelProperty("理科平均录取分数")
        private String lEnrollAvgScore;

        @ApiModelProperty("文科录取数量")
        private String wEnrollNum;

        @ApiModelProperty("理科平均录取分数")
        private String lEnrollAvgScoreDb;

        @ApiModelProperty("文科平均录取分数")
        private String wEnrollAvgScoreDb;

        @ApiModelProperty("理科录取分数")
        private String lEnrollScore;

        @ApiModelProperty("是否文理")
        private Boolean isWl;

        @ApiModelProperty("是否分类录取")
        private Boolean enrollIsCategory;

        @ApiModelProperty("理科平均录取位次")
        private String lEnrollAvgPos;

        @ApiModelProperty("理科录取分数")
        private String lEnrollScoreDb;

        @ApiModelProperty("理科录取数量")
        private String lEnrollNum;

        @ApiModelProperty("文科录取位次")
        private String wEnrollPos;

        @ApiModelProperty("文科平均录取分数")
        private String wEnrollAvgScore;

        @ApiModelProperty("志愿类型")
        private Integer recruitmentVolunteerType;
    }

    @Data
    public static class SubjectInfo {
        @ApiModelProperty("科目信息")
        private KeyData subject;

        @ApiModelProperty("是否首选科目，在3+1+2报考模式下物理、历史为首选科目")
        private Boolean isFirst;
    }
}