package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

import java.util.Arrays;


/**
 * 聊天中的一条消息是谁发的
 */
@AllArgsConstructor
@Getter
public enum MessageFrom {
    BOT(0), CUSTOMER(1);

    @EnumValue
    private final Integer value;

    public static MessageFrom valueOf(Integer value) {
        return Arrays.stream(MessageFrom.values())
                .filter(one -> one.value.equals(value))
                .findFirst().orElse(null);
    }
}
