package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;

@Data
@ApiModel("用户分数信息响应")
public class MemberScoreDetailDTO {
    @ApiModelProperty("c端用户编号")
    private String memberId;

    @ApiModelProperty("c端用户名称")
    private String memberName;

    @ApiModelProperty("用户城市id")
    private String areaId;

    @ApiModelProperty("用户城市name")
    private String areaName;

    @ApiModelProperty("批次信息")
    private KeyData batch;

    @ApiModelProperty("批次等级")
    private KeyData batchLevel;
    @ApiModelProperty("创建时间")
    private Date createTime;

    @ApiModelProperty("志愿填报对应的年份")
    private String dataYear;

    @ApiModelProperty("用户高考年份")
    private String examYear;

    @ApiModelProperty("是否有分数信息")
    private Boolean hasMemberScore;

    @ApiModelProperty("是否vip")
    private Boolean isVip;

    @ApiModelProperty("限制次数, -1则为无限制")
    private Integer limitTimes;

    @ApiModelProperty("民族")
    private KeyData memberNation;

    @ApiModelProperty("c端用户选科关系")
    private List<MemberSubject> memberSubjectList;

    @ApiModelProperty("选科策略 01-文理模式，02-新高考3+1+2模式，03-新高考N选3模式")
    private String policy;

    @ApiModelProperty("位次")
    private Integer pos;

    @ApiModelProperty("推荐批次信息")
    private KeyData recommendBatch;

    @ApiModelProperty("用户分数")
    private String score;

    @ApiModelProperty("选科信息")
    private Type subjectType;

    @ApiModelProperty("还剩多少次修改次数")
    private Integer times;

    @ApiModelProperty("填报类型")
    private Type type;

    @ApiModelProperty(value = "性别")
    private String sex;
    @ApiModelProperty(value = "是否专项")
    private Boolean specialPlan;
    @ApiModelProperty(value = "是否少数民族")
    private Boolean minority;
    @ApiModelProperty(value = "是否色盲色弱")
    private Boolean colorBlindness;
    @ApiModelProperty(value = "是否加分")
    private Boolean bonusPolicy;
    @ApiModelProperty(value = "加分数")
    private BigDecimal bonusScore;


    @Data
    public static class MemberSubject {
        @ApiModelProperty("ID")
        private String id;

        @ApiModelProperty("创建时间")
        private Date createTime;

        @ApiModelProperty("创建人")
        private String createdBy;

        @ApiModelProperty("是否首选科目")
        private Boolean isFirst;

        @ApiModelProperty("用户分数ID")
        private String memberScoreId;

        @ApiModelProperty("选科关联code")
        private KeyData subject;

        @ApiModelProperty(value = "选科的分数")
        private String score;

    }


    @Data
    public static class Type {
        @ApiModelProperty("代码")
        private String code;

        @ApiModelProperty("描述")
        private String desc;
    }
}