package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum MeetingStatus {

    WAIT(0), GOING(1), FINISHED(2);

    @EnumValue
    private final Integer value;


}
