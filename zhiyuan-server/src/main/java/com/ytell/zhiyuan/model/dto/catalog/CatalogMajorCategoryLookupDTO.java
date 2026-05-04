package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

@Data
public class CatalogMajorCategoryLookupDTO {
    private String subCategoryId;
    private String subCategoryName;
    private String categoryId;
    private String categoryName;
    private String educationLevel;
}
