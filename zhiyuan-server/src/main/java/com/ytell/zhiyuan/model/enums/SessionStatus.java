package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum SessionStatus {

    //  WAIT（待沟通）, GOING（沟通中）, FINISHED（已完成）
    WAIT(0), GOING(1), FINISHED(2), CLOSE(3);

    @EnumValue
    private final Integer value;


}
