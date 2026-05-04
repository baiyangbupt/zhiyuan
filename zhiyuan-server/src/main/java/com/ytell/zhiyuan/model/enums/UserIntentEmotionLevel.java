package com.ytell.zhiyuan.model.enums;

/**
 * 用户意向情绪强度枚举
 */
public enum UserIntentEmotionLevel {

    STRONG("Strong", "强烈"),
    NEUTRAL("Neutral", "一般"),
    WEAK("Weak", "轻微");

    private final String value;
    private final String desc;

    UserIntentEmotionLevel(String value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    public String getValue() {
        return value;
    }

    public String getDesc() {
        return desc;
    }

    public static UserIntentEmotionLevel defaultLevel() {
        return STRONG;
    }

    public static String defaultValue() {
        return defaultLevel().value;
    }

    public static UserIntentEmotionLevel fromValue(String value) {
        if (value == null) {
            return defaultLevel();
        }
        for (UserIntentEmotionLevel level : values()) {
            if (level.value.equalsIgnoreCase(value)) {
                return level;
            }
        }
        throw new IllegalArgumentException("Unsupported emotion level: " + value);
    }

    public static UserIntentEmotionLevel safeFromValue(String value) {
        try {
            return fromValue(value);
        } catch (IllegalArgumentException ex) {
            return defaultLevel();
        }
    }
}

