package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.util.List;

/**
 * 专业信息DTO
 */
@Data
public class MajorInfo {

    /**
     * ID
     */
    private String id;

    /**
     * 专业名称
     */
    private String label;

    /**
     * 专业代码（仅三级专业有）
     */
    private String majorCode;

    /**
     * 父级ID
     */
    private String parentId;

    /**
     * 是否关注
     */
    private boolean isAttention;

    /**
     * 子级专业列表
     */
    private List<MajorInfo> children;
} 