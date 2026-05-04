package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;
import org.hibernate.validator.constraints.Length;

import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import java.io.Serializable;
import java.math.BigDecimal;
import java.util.List;

@Data
@ApiModel(value = "VolunteerProgramSaveDTO", description = "填报方案保存请求")
public class VolunteerProgramSaveDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    // 更新时，id必传
    @ApiModelProperty(value = "ID")
    private Long id;

    @ApiModelProperty(value = "学生ID")
    @NotNull(message = "学生ID不能为空")
    private Long memberId;

    @ApiModelProperty(value = "地区")
    @NotNull(message = "地区不能为空")
    private String areaId;

    @ApiModelProperty(value = "高考年份")
    @NotNull(message = "高考年份不能为空")
    private String year;

    @ApiModelProperty(value = "填报推荐策略ID")
    @NotNull(message = "填报推荐策略ID不能为空")
    private Long volunteerPolicyId;

    @ApiModelProperty(value = "来源方案")
    @NotNull(message = "来源方案不能为空")
    private Long parentId;

    @ApiModelProperty(value = "名称")
    @NotNull(message = "名称不能为空")
    @Length(max = 100, message = "名称长度不能超过100")
    private String name;

    @ApiModelProperty(value = "批次")
    @NotNull(message = "批次不能为空")
    private KeyData batch;

    @ApiModelProperty(value = "文理分科")
    @NotNull(message = "文理分科不能为空")
    private String subjectType;

    @ApiModelProperty(value = "分数")
    @NotNull(message = "分数不能为空")
    private BigDecimal score;

    @ApiModelProperty(value = "位次")
    @NotNull(message = "位次不能为空")
    private Integer pos;

    @ApiModelProperty(value = "填报类型")
    @NotNull(message = "填报类型不能为空")
    private String type;

    @ApiModelProperty(value = "填报方式")
    @NotNull(message = "填报方式不能为空")
    private String manner;

    @ApiModelProperty(value = "专家ID")
    @NotNull(message = "专家ID不能为空")
    private Long expertUserId;

    @ApiModelProperty(value = "填报方案院校")
    @NotEmpty(message = "填报方案院校不能为空")
    private List<VolunteerProgramSchoolSaveDTO> schoolSaveDTOList;

    @ApiModelProperty(value = "填报方案专业")
    @NotEmpty(message = "填报方案专业不能为空")
    private List<VolunteerProgramMajorSaveDTO> majorSaveDTOList;

    @ApiModelProperty(value = "填报方案选科关系")
    @NotEmpty(message = "填报方案选科关系不能为空")
    private List<VolunteerProgramSubjectSaveDTO> subjectSaveDTOList;
}