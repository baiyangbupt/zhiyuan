package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum BaikeTagPropertyType {
    STATIC(0), DYNASTIC(1);
    @EnumValue
    private final Integer dbValue;
}
