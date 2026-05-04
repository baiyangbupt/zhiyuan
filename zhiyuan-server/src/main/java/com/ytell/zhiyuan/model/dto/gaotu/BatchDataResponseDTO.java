package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.io.Serializable;
import java.util.List;

@Data
@ApiModel(value = "BatchDataResponseDTO", description = "批次线数据响应")
public class BatchDataResponseDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "当前年份")
    private String year;

    @ApiModelProperty(value = "招生计划年份")
    private String baseYear;

    @ApiModelProperty(value = "换算年份")
    private String converYear;

    @ApiModelProperty(value = "地区")
    private KeyData area;

    @ApiModelProperty(value = "批次列表")
    private List<BatchInfo> batchList;

    @ApiModelProperty(value = "方案展示类型")
    private TypeInfo type;

    @Data
    public static class BatchInfo implements Serializable {
        @ApiModelProperty(value = "批次数据ID")
        private String id;

        @ApiModelProperty(value = "批次数据年份")
        private String year;

        @ApiModelProperty(value = "批次编码")
        private String batch;

        @ApiModelProperty(value = "批次线名称")
        private String batchTitle;

        @ApiModelProperty(value = "批次线分数")
        private String score;

        @ApiModelProperty(value = "批次线对应的位次")
        private Integer pos;

        @ApiModelProperty(value = "当前选科")
        private TypeInfo subject;

        @ApiModelProperty(value = "批次对应本专科")
        private KeyData level;
    }

    @Data
    public static class TypeInfo implements Serializable {
        @ApiModelProperty(value = "编码")
        private String code;

        @ApiModelProperty(value = "描述")
        private String desc;
    }
}