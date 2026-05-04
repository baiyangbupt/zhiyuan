package com.ytell.zhiyuan.common.ali;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "ali.oss")
public class OssProperties {

    public String accessKeyId;

    public String accessKeySecret;

    public String endpoint;
    public String region;
    public String bucket;

}
