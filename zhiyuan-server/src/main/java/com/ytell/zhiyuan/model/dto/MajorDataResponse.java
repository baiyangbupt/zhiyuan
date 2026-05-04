package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.util.List;

/**
 * 专业数据响应包装类
 */
@Data
public class MajorDataResponse {

    /**
     * 响应码
     */
    private int code;

    /**
     * 专业数据列表
     */
    private List<MajorInfo> data;
} 