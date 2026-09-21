package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.Date;
import java.util.Map;

/**
 * 会话产物对外的样子。**不含** frozen 命令与个人资料全文——
 * 那两样属于内部事务，映射到公开 DTO 时不出现在这里。
 */
@Data
public class ArtifactDTO {
    private String artifactId;
    private String kind;
    private Map<String, Object> payload;
    private Map<String, Object> dependencies;
    private String payloadDigest;
    private Date expiresAt;
    private Date createdAt;
}
