package com.ytell.zhiyuan.model.vo;

import lombok.Data;

import java.util.List;

/**
 * 省市数据响应VO
 */
@Data
public class ProvinceCityResponseVO {

    /**
     * 响应码
     */
    private Integer code;

    /**
     * 省市数据列表
     */
    private List<ProvinceCityVO> data;

    /**
     * 响应消息
     */
    private String msg;

    /**
     * 时间戳
     */
    private Long timestamp;

    /**
     * 错误消息
     */
    private String errorMsg;

    /**
     * 是否成功
     */
    private Boolean isSuccess;
}
