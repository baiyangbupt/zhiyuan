package com.ytell.zhiyuan.model.dto;

import lombok.Data;

/**
 * 就业率DTO
 */
@Data
public class EmploymentRateDTO {

    /**
     * 年份
     */
    private Integer year;

    /**
     * 就业率
     */
    private String rate;

    public EmploymentRateDTO() {
    }

    public EmploymentRateDTO(Integer year, String rate) {
        this.year = year;
        this.rate = rate;
    }
}
