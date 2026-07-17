package com.ytell.zhiyuan.common.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "planning.pending-command.retention")
public class PlanningPendingCommandRetentionProperties {
    private Boolean enabled = true;
    private Integer retentionDays = 30;
    private Integer batchSize = 500;
}
