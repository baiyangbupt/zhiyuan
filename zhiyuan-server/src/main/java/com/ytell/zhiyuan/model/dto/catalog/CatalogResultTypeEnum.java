package com.ytell.zhiyuan.model.dto.catalog;

import com.fasterxml.jackson.annotation.JsonValue;

public enum CatalogResultTypeEnum {
    EXACT("exact"),
    MULTI("multi"),
    EMPTY("empty");

    private final String value;

    CatalogResultTypeEnum(String value) {
        this.value = value;
    }

    @JsonValue
    public String getValue() {
        return value;
    }
}
