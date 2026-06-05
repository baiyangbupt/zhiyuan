package com.ytell.zhiyuan.common.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "gaotu.zhiyuan")
public class GaotuProperties {
    private String zhiyuanUrl;
    private String userUrl;
    private String riskUrl;
    private String evn;
    private Boolean riskOpen;
    private Boolean authOpen;
    private String tempDataPath;

}
