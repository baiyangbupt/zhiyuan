package com.ytell.zhiyuan.model.enums;

import java.util.Arrays;

/**
 * 用户意向维度类型
 */
public enum UserIntentDimension {

    CITY_PROVINCE("cityProvince"),
    CITY_CITY("cityCity"),
    COLLEGE("college"),
    TAG("tag"),
    MAJOR_LEVEL2("majorLevel2"),
    MAJOR_LEVEL3("majorLevel3");

    private final String code;

    UserIntentDimension(String code) {
        this.code = code;
    }

    public String getCode() {
        return code;
    }

    public static UserIntentDimension fromCode(String code) {
        if (code == null) {
            return null;
        }
        return Arrays.stream(values())
                .filter(item -> item.code.equalsIgnoreCase(code))
                .findFirst()
                .orElse(null);
    }
}

