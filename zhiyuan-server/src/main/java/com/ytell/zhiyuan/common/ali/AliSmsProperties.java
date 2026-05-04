package com.ytell.zhiyuan.common.ali;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "ali.sms")
public class AliSmsProperties {
    public String accessKeyId;
    public String accessKeySecret;
    public String endpoint;
    public String signName;
    public String template;

}
