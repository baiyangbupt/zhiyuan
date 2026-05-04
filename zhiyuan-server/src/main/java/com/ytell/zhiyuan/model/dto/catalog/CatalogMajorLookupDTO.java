package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

@Data
public class CatalogMajorLookupDTO {
    private String majorId;
    private String majorName;
    private String majorUnitCode;
    private String subCategoryId;
    private String subCategoryName;
    private String categoryId;
    private String categoryName;
    private String educationLevel;
}
