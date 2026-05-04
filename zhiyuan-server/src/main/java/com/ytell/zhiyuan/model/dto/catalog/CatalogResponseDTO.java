package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

@Data
public class CatalogResponseDTO<T> {
    private String catalogVersion;
    private String schemaVersion;
    private CatalogResultTypeEnum resultType;
    private T data;
}
