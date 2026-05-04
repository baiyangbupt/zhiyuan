package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class CatalogMajorTreeNodeDTO {
    private String categoryId;
    private String categoryName;
    private List<CatalogMajorCategoryNodeDTO> children = new ArrayList<>();
}
