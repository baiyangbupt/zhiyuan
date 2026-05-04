package com.ytell.zhiyuan.model.dto.inner;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
@ApiModel("志愿方案参数可用性检查请求")
public class PlanParamAvailReq {

    @ApiModelProperty("会话ID")
    private String chatSessionId;

    @ApiModelProperty("专业信息，按志愿等级分类")
    private Map<String, List<String>> majors;

    @ApiModelProperty("学校名称列表")
    private List<String> schools;

    @ApiModelProperty("地区信息")
    private LocationInfo locations;

    @Data
    @ApiModel("地区信息")
    public static class LocationInfo {
        @ApiModelProperty("省份列表")
        private List<String> province;

        @ApiModelProperty("城市列表")
        private List<String> city;
    }
}
