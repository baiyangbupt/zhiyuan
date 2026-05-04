package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

@Data
public class CatalogMajorSearchItemDTO {
    private CatalogMatchTypeEnum matchType;
    private String majorId;
    private String majorName;
    private String subCategoryId;
    private String subCategoryName;
    private String categoryId;
    private String categoryName;
    private String educationLevel;
}
