package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.config.PlanningPendingCommandRetentionProperties;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.concurrent.atomic.AtomicBoolean;

@Slf4j
@Component
@EnableConfigurationProperties(PlanningPendingCommandRetentionProperties.class)
public class PlanningPendingCommandRetentionTask {

    private static final long MILLIS_PER_DAY = 24L * 60L * 60L * 1000L;

    @Autowired
    private PlanningPendingCommandRetentionProperties properties;

    @Autowired
    private PlanningPendingCommandSharedService commandSharedService;

    private final AtomicBoolean running = new AtomicBoolean(false);

    @Scheduled(fixedDelayString = "${planning.pending-command.retention.fixed-delay-ms:3600000}")
    public void run() {
        if (!Boolean.TRUE.equals(properties.getEnabled()) || !running.compareAndSet(false, true)) {
            return;
        }
        try {
            int retentionDays = Math.max(1, defaultInteger(properties.getRetentionDays(), 30));
            int batchSize = Math.max(1, defaultInteger(properties.getBatchSize(), 500));
            Date cutoff = new Date(System.currentTimeMillis() - retentionDays * MILLIS_PER_DAY);
            int deleted = commandSharedService.deleteSucceededUpdatedBefore(cutoff, batchSize);
            if (deleted > 0) {
                log.info("planningPendingCommandRetention deleted={} retentionDays={} batchSize={}",
                        deleted, retentionDays, batchSize);
            }
        } catch (Exception ex) {
            log.error("planningPendingCommandRetention failed", ex);
        } finally {
            running.set(false);
        }
    }

    private int defaultInteger(Integer value, int defaultValue) {
        return value == null ? defaultValue : value;
    }
}
