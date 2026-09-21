package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class ArtifactPageDTO {
    private String artifactId;
    private String kind;
    private List<Map<String, Object>> items;
    private Integer total;
    private String nextCursor;
    private String payloadDigest;
}
