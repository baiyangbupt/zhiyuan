package com.ytell.zhiyuan.model.dto.inner;

import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 志愿数据 DTO
 * 用于替代 JSONObject，提供更好的类型安全和取值便利性
 */
@Data
@ApiModel("志愿数据 DTO")
public class VolunteerDataDTO {

    @ApiModelProperty("方案模型")
    private ProgramPageDTO.ProgramModel model;

    @ApiModelProperty("方案详细内容")
    private java.util.List<ProgramPageDTO.SchoolDetail> detailList;

    @ApiModelProperty("数据类型")
    private ProgramPageDTO.Type type;

    @ApiModelProperty("选科策略，01-老高考文理，02-3+1+2，03-N选3")
    private String policy;

    @ApiModelProperty("方案策略是否为最新策略")
    private Boolean isLatestPolicy;

    @ApiModelProperty("数据展示类型")
    private com.ytell.zhiyuan.model.dto.gaotu.KeyData modeEnum;
}
