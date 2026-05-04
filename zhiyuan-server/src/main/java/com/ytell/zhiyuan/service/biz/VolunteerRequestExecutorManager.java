package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.config.VolunteerRankProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import javax.annotation.PreDestroy;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * 志愿请求线程池管理器
 * 负责管理和维护志愿排序请求的线程池
 *
 * 使用示例：
 * 1. 注入管理器：@Autowired private VolunteerRequestExecutorManager executorManager;
 * 2. 获取线程池：ExecutorService executor = executorManager.getExecutor();
 * 3. 使用线程池：CompletableFuture.supplyAsync(task, executor);
 * 4. 查看状态：String status = executorManager.getExecutorStatus();
 *
 * 特性：
 * - 自动检测配置变化并重新创建线程池
 * - 线程安全，支持并发访问
 * - 应用启动/关闭时自动管理生命周期
 * - 提供状态监控功能
 */
@Slf4j
@Component
public class VolunteerRequestExecutorManager {

    @Autowired
    private VolunteerRankProperties volunteerRankProperties;

    // 线程池实例，避免每次都创建新的线程池
    private volatile ExecutorService requestExecutor;

    // 记录当前的并发数配置，用于检测配置变化
    private volatile int currentMaxConcurrentRequests;

    /**
     * 初始化线程池
     */
    @PostConstruct
    private void initializeExecutor() {
        // 初始化时设置当前并发数配置
        this.currentMaxConcurrentRequests = volunteerRankProperties.getMaxConcurrentRequests() != null
            ? volunteerRankProperties.getMaxConcurrentRequests()
            : Runtime.getRuntime().availableProcessors();

        this.requestExecutor = createRequestExecutor();
        log.info("VolunteerRequestExecutorManager 线程池初始化完成，并发数: {}", currentMaxConcurrentRequests);
    }

    /**
     * 获取线程池实例，如果为null或配置发生变化则创建新的
     */
    public ExecutorService getExecutor() {
        int newMaxConcurrentRequests = volunteerRankProperties.getMaxConcurrentRequests() != null
            ? volunteerRankProperties.getMaxConcurrentRequests()
            : Runtime.getRuntime().availableProcessors();

        // 检查配置是否发生变化
        if (requestExecutor == null || newMaxConcurrentRequests != currentMaxConcurrentRequests) {
            synchronized (this) {
                if (requestExecutor == null || newMaxConcurrentRequests != currentMaxConcurrentRequests) {
                    ExecutorService oldExecutor = requestExecutor;
                    requestExecutor = createRequestExecutor();
                    currentMaxConcurrentRequests = newMaxConcurrentRequests;

                    // 关闭旧的线程池
                    if (oldExecutor != null) {
                        oldExecutor.shutdown();
                        try {
                            if (!oldExecutor.awaitTermination(10, TimeUnit.SECONDS)) {
                                oldExecutor.shutdownNow();
                                log.warn("旧线程池未在指定时间内正常关闭，强制关闭");
                            }
                        } catch (InterruptedException e) {
                            oldExecutor.shutdownNow();
                            Thread.currentThread().interrupt();
                        }
                    }

                    log.info("线程池已重新创建，并发数: {}", currentMaxConcurrentRequests);
                }
            }
        }
        return requestExecutor;
    }

    /**
     * 当配置发生变化时，重新创建线程池
     * 注意：这是一个示例方法，实际使用时可能需要通过配置中心或事件监听来调用
     */
    public void recreateExecutorIfNeeded() {
        synchronized (this) {
            ExecutorService oldExecutor = this.requestExecutor;
            this.requestExecutor = createRequestExecutor();

            // 关闭旧的线程池
            if (oldExecutor != null) {
                oldExecutor.shutdown();
                try {
                    if (!oldExecutor.awaitTermination(30, TimeUnit.SECONDS)) {
                        oldExecutor.shutdownNow();
                        log.warn("旧线程池未在指定时间内正常关闭，强制关闭");
                    }
                } catch (InterruptedException e) {
                    oldExecutor.shutdownNow();
                    Thread.currentThread().interrupt();
                }
                log.info("线程池已重新创建");
            }
        }
    }

    /**
     * 应用销毁时清理线程池
     */
    @PreDestroy
    private void destroyExecutor() {
        if (requestExecutor != null) {
            requestExecutor.shutdown();
            try {
                if (!requestExecutor.awaitTermination(30, TimeUnit.SECONDS)) {
                    requestExecutor.shutdownNow();
                    log.warn("销毁时线程池未在指定时间内正常关闭，强制关闭");
                }
            } catch (InterruptedException e) {
                requestExecutor.shutdownNow();
                Thread.currentThread().interrupt();
            }
            log.info("VolunteerRequestExecutorManager 线程池已销毁");
        }
    }

    /**
     * 获取当前线程池状态信息
     * @return 状态信息
     */
    public String getExecutorStatus() {
        if (requestExecutor == null) {
            return "线程池未初始化";
        }
        java.util.concurrent.ThreadPoolExecutor executor = (java.util.concurrent.ThreadPoolExecutor) requestExecutor;
        return String.format("线程池状态: 最大并发数=%d, 活跃线程数=%d, 队列大小=%d, 完成任务数=%d",
            currentMaxConcurrentRequests,
            executor.getActiveCount(),
            executor.getQueue().size(),
            executor.getCompletedTaskCount());
    }

    /**
     * 创建用于并发请求的线程池
     * @return ExecutorService 线程池
     */
    private ExecutorService createRequestExecutor() {
        int maxConcurrentRequests = volunteerRankProperties.getMaxConcurrentRequests() != null
            ? volunteerRankProperties.getMaxConcurrentRequests()
            : Runtime.getRuntime().availableProcessors(); // 默认使用CPU核心数

        log.debug("创建线程池，并发数限制: {}", maxConcurrentRequests);

        return Executors.newFixedThreadPool(maxConcurrentRequests,
            r -> {
                Thread t = new Thread(r, "volunteer-rank-" + System.currentTimeMillis());
                t.setDaemon(true);
                return t;
            });
    }
}
