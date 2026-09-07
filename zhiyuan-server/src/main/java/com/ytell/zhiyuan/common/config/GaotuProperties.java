package com.ytell.zhiyuan.common.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "gaotu.zhiyuan")
public class GaotuProperties {
    private String zhiyuanUrl;
    private String programDataUrl;
    private String userUrl;
    private String riskUrl;
    private String evn;
    private Boolean riskOpen;
    private Boolean authOpen;
    private String tempDataPath;
    private Boolean programDataPagedEnabled = true;
    private Boolean programDataFallbackEnabled = true;
    private Integer programDataPageRetryTimes = 2;
    private Integer programDataSessionReinitTimes = 1;
    private Integer programDataPageConcurrency = 1;

}
