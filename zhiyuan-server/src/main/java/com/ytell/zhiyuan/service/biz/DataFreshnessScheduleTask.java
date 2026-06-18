package com.ytell.zhiyuan.service.biz;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ytell.zhiyuan.common.config.DataFreshnessScheduleProperties;
import com.ytell.zhiyuan.model.entity.biz.PlanningDataFreshnessScheduleEntity;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.model.req.ChatSessionPageQuery;
import com.ytell.zhiyuan.service.shared.PlanningDataFreshnessScheduleSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

@Slf4j
@Component
@EnableConfigurationProperties(DataFreshnessScheduleProperties.class)
public class DataFreshnessScheduleTask {

    @Autowired
    private DataFreshnessScheduleProperties properties;

    @Autowired
    private PlanningDataFreshnessScheduleSharedService planningDataFreshnessScheduleSharedService;

    @Autowired
    private PlanningStateService planningStateService;

    @Autowired
    private ChatSessionSharedService chatSessionSharedService;

    private final AtomicBoolean running = new AtomicBoolean(false);
    private int seedPageCursor = 1;

    @Scheduled(fixedDelayString = "${planning.data-freshness.schedule.fixed-delay-ms:300000}")
    public void run() {
        if (!Boolean.TRUE.equals(properties.getEnabled())) {
            return;
        }
        if (!running.compareAndSet(false, true)) {
            return;
        }
        try {
            seedRecentSupportedSchedules();
            executeDueChecks();
        } finally {
            running.set(false);
        }
    }

    private void executeDueChecks() {
        int batchSize = Math.max(1, defaultInteger(properties.getBatchSize(), 5));
        int maxTasks = Math.max(1, defaultInteger(properties.getMaxConsecutiveTasks(), 2));
        List<PlanningDataFreshnessScheduleEntity> dueList = planningDataFreshnessScheduleSharedService.listDue(new Date(), batchSize);
        int executed = 0;
        for (PlanningDataFreshnessScheduleEntity entity : dueList) {
            if (entity == null || entity.getChatSessionId() == null || entity.getTenantId() == null) {
                continue;
            }
            if (!DataFreshnessSchedulePolicy.isBackgroundEligible(entity.getPrepareType(), entity.getSessionStatus())) {
                continue;
            }
            planningStateService.checkDataFreshnessLightweightForSchedule(
                    entity.getTenantId(),
                    entity.getChatSessionId(),
                    "scheduler"
            );
            executed++;
            if (executed >= maxTasks) {
                break;
            }
        }
        if (executed > 0) {
            log.info("dataFreshnessSchedule executed dueChecks={}", executed);
        }
    }

    private void seedRecentSupportedSchedules() {
        int seedBatchSize = Math.max(1, defaultInteger(properties.getSeedBatchSize(), 10));
        ChatSessionPageQuery req = new ChatSessionPageQuery();
        req.setPage(seedPageCursor);
        req.setPageSize(seedBatchSize);
        req.setStatusList(Arrays.asList(SessionStatus.GOING, SessionStatus.WAIT));
        Page<ChatSession> page = chatSessionSharedService.pageSession(null, req);
        if (page == null || page.getRecords() == null || page.getRecords().isEmpty()) {
            seedPageCursor = 1;
            return;
        }
        int seeded = 0;
        for (ChatSession session : page.getRecords()) {
            if (session == null || session.getId() == null) {
                continue;
            }
            if (planningDataFreshnessScheduleSharedService.getByChatSessionId(session.getId()) != null) {
                continue;
            }
            planningStateService.ensureDataFreshnessScheduleIndex(session.getTenantId(), session.getId());
            seeded++;
        }
        seedPageCursor = page.getPages() > 0 && seedPageCursor >= page.getPages() ? 1 : seedPageCursor + 1;
        if (seeded > 0) {
            log.info("dataFreshnessSchedule seeded schedules={} page={}", seeded, req.getPage());
        }
    }

    private int defaultInteger(Integer value, int defaultValue) {
        return value == null ? defaultValue : value;
    }
}
