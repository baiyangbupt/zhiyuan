package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum TargetType {
    SCHOOL_FIRST("schoolFirst", "学校优先"),
    MAJOR_FIRST("majorFirst", "专业优先"),
    CITY_FIRST("cityFirst", "城市优先");

    @EnumValue
    private final String code;
    private final String desc;
}
