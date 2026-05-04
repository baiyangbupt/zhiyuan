package com.ytell.zhiyuan.model.dto.gaotu;

import com.alibaba.fastjson.JSONArray;
import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.io.Serializable;

@Data
@ApiModel(value = "GetReportInfoRpcVO", description = "获取测评报告详细信息响应参数")
public class GetReportInfoDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "报告类型")
    private Long reportType;

    @ApiModelProperty(value = "报告结果")
    private JSONArray results;

    @Data
    @ApiModel(value = "MajorsRecommendDTO", description = "专业推荐数据")
    public static class MajorsRecommendDTO implements Serializable {

        private static final long serialVersionUID = 1L;

        @ApiModelProperty(value = "类目 电子商务类/化学工艺")
        private String category;

        @ApiModelProperty(value = "匹配程度(百分比) 100%")
        private Double matchDegree;

        @ApiModelProperty(value = "学制 eg: 五年")
        private String duration;
    }
}