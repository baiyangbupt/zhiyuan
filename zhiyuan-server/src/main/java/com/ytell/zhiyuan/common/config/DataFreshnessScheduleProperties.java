package com.ytell.zhiyuan.common.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "planning.data-freshness.schedule")
public class DataFreshnessScheduleProperties {
    private Boolean enabled = false;
    private Long fixedDelayMs = 300000L;
    private Integer batchSize = 5;
    private Integer seedBatchSize = 10;
    private Integer maxConsecutiveTasks = 2;
}
