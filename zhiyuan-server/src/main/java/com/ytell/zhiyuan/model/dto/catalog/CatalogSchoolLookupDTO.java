package com.ytell.zhiyuan.model.dto.catalog;

import lombok.Data;

@Data
public class CatalogSchoolLookupDTO {
    private String schoolId;
    private String schoolName;
    private String schoolUnitCode;
    private String provinceCode;
    private String provinceName;
    private String cityCode;
    private String cityName;
}
