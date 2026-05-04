package com.ytell.zhiyuan.model.enums;

/**
 * 用户意向正负向标识
 */
public enum UserIntentPolarity {

    POSITIVE,
    NEGATIVE;

    public static UserIntentPolarity fromValue(String value) {
        if (value == null) {
            return null;
        }
        for (UserIntentPolarity polarity : values()) {
            if (polarity.name().equalsIgnoreCase(value)) {
                return polarity;
            }
        }
        return null;
    }
}

