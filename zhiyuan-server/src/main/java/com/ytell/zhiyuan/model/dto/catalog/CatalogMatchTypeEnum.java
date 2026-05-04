package com.ytell.zhiyuan.model.dto.catalog;

import com.fasterxml.jackson.annotation.JsonValue;

public enum CatalogMatchTypeEnum {
    EXACT("exact"),
    ALIAS("alias"),
    FUZZY("fuzzy");

    private final String value;

    CatalogMatchTypeEnum(String value) {
        this.value = value;
    }

    @JsonValue
    public String getValue() {
        return value;
    }
}
