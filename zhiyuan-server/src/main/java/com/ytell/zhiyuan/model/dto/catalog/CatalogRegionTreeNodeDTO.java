package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class CatalogRegionTreeNodeDTO {
    private String provinceCode;
    private String provinceName;
    private List<CatalogRegionCityNodeDTO> children = new ArrayList<>();
}
