package com.ytell.zhiyuan.model.dto.gaotu.res;

import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
public class QueryProgramByLimitNumRes {

    @ApiModelProperty(value = "志愿级别")
    private String volunteerLevel;

    @ApiModelProperty(value = "学校记录列表")
    private List<SchoolRecordDTO> records;
} 