package com.ytell.zhiyuan.model.dto.inner;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
@ApiModel("专业选课可用性检查请求")
public class MajorSubjectAvailReq {

    @ApiModelProperty("会话ID")
    private String chatSessionId;

    @ApiModelProperty("专业信息，按志愿等级分类")
    private Map<String, List<String>> majors;
}
