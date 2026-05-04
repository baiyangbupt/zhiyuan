package com.ytell.zhiyuan.common.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.SchedulingConfigurer;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.scheduling.config.ScheduledTaskRegistrar;

import java.util.concurrent.ThreadPoolExecutor;


@Configuration
public class ScheduleConfig implements SchedulingConfigurer {

    @Override
    public void configureTasks(ScheduledTaskRegistrar taskRegistrar) {
        ThreadPoolTaskScheduler scheduler = new ThreadPoolTaskScheduler();
        scheduler.initialize();
        scheduler.setPoolSize(20);
        scheduler.setThreadNamePrefix("schedule-task-");
        scheduler.setRejectedExecutionHandler(new ThreadPoolExecutor.DiscardOldestPolicy());
        taskRegistrar.setScheduler(scheduler);
    }
}


