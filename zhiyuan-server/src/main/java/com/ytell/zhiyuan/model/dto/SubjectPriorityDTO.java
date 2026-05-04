package com.ytell.zhiyuan.model.dto;

import lombok.Data;

/**
 * 学科优先级DTO
 */
@Data
public class SubjectPriorityDTO {

    /**
     * 学科名称
     */
    private String subject;

    /**
     * 权重比例
     */
    private Double ratio;

    public SubjectPriorityDTO() {
    }

    public SubjectPriorityDTO(String subject, Double ratio) {
        this.subject = subject;
        this.ratio = ratio;
    }
}
