package com.ytell.zhiyuan.common.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 志愿排名服务配置
 */
@Data
@ConfigurationProperties(prefix = "volunteer.rank")
public class VolunteerRankProperties {

    /**
     * 志愿排名服务基础URL
     */
    private String url;

    /**
     * 环境标识
     */
    private String env;

    /**
     * 并发请求数限制，默认值为CPU核心数
     */
    private Integer maxConcurrentRequests;
}
