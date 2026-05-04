package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

@Data
public class CatalogSchoolSearchItemDTO {
    private CatalogMatchTypeEnum matchType;
    private String schoolId;
    private String schoolName;
}
