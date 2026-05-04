package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;
import org.hibernate.validator.constraints.Length;

import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import java.io.Serializable;

@Data
@ApiModel(value = "VolunteerProgramSubjectSaveDTO", description = "填报方案选科关系")
public class VolunteerProgramSubjectSaveDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "选科关联")
    @NotEmpty(message = "选科关联不能为空")
    @Length(max = 2, message = "选科关联长度不能超过2")
    private KeyData subject;

    @ApiModelProperty(value = "是否首选")
    @NotNull(message = "是否首选不能为空")
    private Boolean isFirst;


}