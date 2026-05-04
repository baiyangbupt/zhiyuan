package com.ytell.zhiyuan.model.dto;

import lombok.Data;

/**
 * 用户意向值及情绪明细
 */
@Data
public class UserIntentValueDetail {

    /**
     * 维度标识
     */
    private String dimension;

    /**
     * 正负向
     */
    private String polarity;

    /**
     * 展示名称
     */
    private String label;

    /**
     * 对应编码
     */
    private String code;

    /**
     * 情绪强度（英文枚举值）
     */
    private String emotion;

    /**
     * 情绪描述（中文）
     */
    private String emotionDesc;
}

