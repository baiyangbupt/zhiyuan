package com.ytell.zhiyuan.common.ali;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "ali.oss")
public class OssProperties {

    /** Explicitly disable all remote OSS operations in isolated environments. */
    private boolean enabled = true;

    /** Optional object-key prefix for an isolated environment. Empty preserves legacy keys. */
    private String namespace;

    public String accessKeyId;

    public String accessKeySecret;

    public String endpoint;
    public String region;
    public String bucket;

}
