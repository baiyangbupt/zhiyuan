package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 解读卡的有界 caveat：正文仍保留扁平 strings（旧消费者兼容），
 * 该结构只用于前端按 hard/soft 分组展示。
 */
@Data
public class InterpretationCaveatDTO {
    private String text;
    /** hard = 硬性要求未满足；soft = 建议/数据缺口提醒。 */
    private String level;
    /** 评价 finding 的 probe code（数据缺口类可为空）。 */
    private String code;
}
