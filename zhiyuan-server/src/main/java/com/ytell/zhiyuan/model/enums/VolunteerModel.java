package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum VolunteerModel {

    majorGroup("majorGroup", "专业组"),
    major("major", "专业+院校");
    @EnumValue
    private final String code;
    private final String desc;
}
