package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.mapper.PlanningDataFreshnessScheduleMapper;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessScheduleDTO;
import com.ytell.zhiyuan.model.entity.biz.PlanningDataFreshnessScheduleEntity;
import com.ytell.zhiyuan.service.biz.DataFreshnessSchedulePolicy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.Date;
import java.util.List;

@Slf4j
@Service
public class PlanningDataFreshnessScheduleSharedService extends ServiceImpl<PlanningDataFreshnessScheduleMapper, PlanningDataFreshnessScheduleEntity> {

    public PlanningDataFreshnessScheduleEntity getByChatSessionId(Long chatSessionId) {
        if (chatSessionId == null) {
            return null;
        }
        QueryWrapper<PlanningDataFreshnessScheduleEntity> queryWrapper = new QueryWrapper<PlanningDataFreshnessScheduleEntity>();
        queryWrapper.lambda().eq(PlanningDataFreshnessScheduleEntity::getChatSessionId, chatSessionId);
        queryWrapper.lambda().last(" limit 1");
        return this.getOne(queryWrapper);
    }

    public PlanningDataFreshnessScheduleEntity saveOrUpdateSchedule(PlanningDataFreshnessScheduleEntity incoming) {
        if (incoming == null || incoming.getChatSessionId() == null) {
            return incoming;
        }
        Date now = new Date();
        PlanningDataFreshnessScheduleEntity existing = getByChatSessionId(incoming.getChatSessionId());
        if (existing == null) {
            fillDefaults(incoming, now);
            try {
                this.save(incoming);
                return incoming;
            } catch (DuplicateKeyException e) {
                // 并发首读（workspace-state 懒触达）会同时走到这里，唯一键
                // uk_planning_data_freshness_schedule_session 让其中一个 insert 失败；
                // 退回"读赢家 + 合并更新"，避免直接把 500/code -1 抛给前端。
                PlanningDataFreshnessScheduleEntity winner = getByChatSessionId(incoming.getChatSessionId());
                if (winner == null) {
                    throw e;
                }
                log.info("saveOrUpdateSchedule lost insert race chatSessionId={} fallback=update",
                        incoming.getChatSessionId());
                merge(winner, incoming);
                fillDefaults(winner, now);
                this.updateById(winner);
                return winner;
            }
        }
        merge(existing, incoming);
        fillDefaults(existing, now);
        this.updateById(existing);
        return existing;
    }

    public List<PlanningDataFreshnessScheduleEntity> listDue(Date now, int limit) {
        QueryWrapper<PlanningDataFreshnessScheduleEntity> queryWrapper = new QueryWrapper<PlanningDataFreshnessScheduleEntity>();
        queryWrapper.lambda().eq(PlanningDataFreshnessScheduleEntity::getEnabled, true);
        queryWrapper.lambda().and(wrapper -> wrapper
                .isNull(PlanningDataFreshnessScheduleEntity::getLastCheckedAt)
                .or()
                .le(PlanningDataFreshnessScheduleEntity::getNextCheckAt, now)
                .or()
                .le(PlanningDataFreshnessScheduleEntity::getLastCheckedAt,
                        new Date(now.getTime() - DataFreshnessSchedulePolicy.MAX_INTERVAL_MINUTES * 60L * 1000L)));
        queryWrapper.lambda()
                .orderByAsc(PlanningDataFreshnessScheduleEntity::getProvinceCode)
                .orderByAsc(PlanningDataFreshnessScheduleEntity::getSessionCreateTime)
                .orderByAsc(PlanningDataFreshnessScheduleEntity::getChatSessionId);
        queryWrapper.lambda().last(" limit " + Math.max(1, limit));
        return this.list(queryWrapper);
    }

    public void markChecking(Long chatSessionId) {
        PlanningDataFreshnessScheduleEntity entity = getByChatSessionId(chatSessionId);
        if (entity == null) {
            return;
        }
        entity.setLastCheckStatus("checking");
        this.updateById(entity);
    }

    public void markSuccess(Long chatSessionId, String source, String status, String currentSourceHash, String latestSourceHash, Date checkedAt) {
        PlanningDataFreshnessScheduleEntity entity = getByChatSessionId(chatSessionId);
        if (entity == null) {
            return;
        }
        Date now = checkedAt == null ? new Date() : checkedAt;
        int interval = DataFreshnessSchedulePolicy.calculateIntervalMinutes(
                entity.getSessionCreateTime(),
                entity.getLastAccessedAt(),
                entity.getSessionStatus(),
                now
        );
        entity.setCheckIntervalMinutes(interval);
        entity.setLastCheckedAt(now);
        entity.setNextCheckAt(DataFreshnessSchedulePolicy.calculateNextCheckAt(now, interval, now));
        entity.setLastCheckSource(source);
        entity.setLastCheckStatus(status);
        entity.setLatestSourceDataHash(latestSourceHash);
        if (currentSourceHash != null && !currentSourceHash.trim().isEmpty()) {
            entity.setSourceDataHash(currentSourceHash);
        } else if ((entity.getSourceDataHash() == null || entity.getSourceDataHash().trim().isEmpty())
                && latestSourceHash != null && !latestSourceHash.trim().isEmpty()) {
            entity.setSourceDataHash(latestSourceHash);
        }
        entity.setFailCount(0);
        entity.setLastError(null);
        entity.setLastFailedAt(null);
        this.updateById(entity);
    }

    public void markFailure(Long chatSessionId, String source, String error, Date failedAt) {
        PlanningDataFreshnessScheduleEntity entity = getByChatSessionId(chatSessionId);
        if (entity == null) {
            return;
        }
        Date now = failedAt == null ? new Date() : failedAt;
        int currentFailCount = entity.getFailCount() == null ? 0 : entity.getFailCount();
        int nextFailCount = currentFailCount + 1;
        int baseInterval = DataFreshnessSchedulePolicy.calculateIntervalMinutes(
                entity.getSessionCreateTime(),
                entity.getLastAccessedAt(),
                entity.getSessionStatus(),
                now
        );
        int backoff = Math.min(DataFreshnessSchedulePolicy.MAX_INTERVAL_MINUTES, Math.max(30, nextFailCount * 30));
        int interval = Math.min(DataFreshnessSchedulePolicy.MAX_INTERVAL_MINUTES, Math.min(baseInterval, backoff));
        entity.setCheckIntervalMinutes(interval);
        entity.setNextCheckAt(DataFreshnessSchedulePolicy.calculateNextCheckAt(now, interval, now));
        entity.setLastCheckSource(source);
        entity.setLastCheckStatus("failed");
        entity.setFailCount(nextFailCount);
        entity.setLastError(truncate(error, 1024));
        entity.setLastFailedAt(now);
        this.updateById(entity);
    }

    public DataFreshnessScheduleDTO toDto(PlanningDataFreshnessScheduleEntity entity) {
        if (entity == null) {
            return null;
        }
        DataFreshnessScheduleDTO dto = new DataFreshnessScheduleDTO();
        dto.setChatSessionId(entity.getChatSessionId());
        dto.setTenantId(entity.getTenantId());
        dto.setPrepareType(entity.getPrepareType());
        dto.setProvinceCode(entity.getProvinceCode());
        dto.setProvinceName(entity.getProvinceName());
        dto.setExamYear(entity.getExamYear());
        dto.setSessionStatus(entity.getSessionStatus());
        dto.setCreateTime(format(entity.getSessionCreateTime()));
        dto.setLastAccessedAt(format(entity.getLastAccessedAt()));
        dto.setLastCheckedAt(format(entity.getLastCheckedAt()));
        dto.setNextCheckAt(format(entity.getNextCheckAt()));
        dto.setCheckIntervalMinutes(entity.getCheckIntervalMinutes());
        dto.setLastCheckSource(entity.getLastCheckSource());
        dto.setLastCheckStatus(entity.getLastCheckStatus());
        dto.setSourceDataHash(entity.getSourceDataHash());
        dto.setLatestSourceDataHash(entity.getLatestSourceDataHash());
        dto.setFailCount(entity.getFailCount());
        dto.setLastError(entity.getLastError());
        dto.setLastFailedAt(format(entity.getLastFailedAt()));
        dto.setEnabled(entity.getEnabled());
        return dto;
    }

    public List<DataFreshnessScheduleDTO> toDtos(List<PlanningDataFreshnessScheduleEntity> entities) {
        List<DataFreshnessScheduleDTO> result = Lists.newArrayList();
        if (entities == null) {
            return result;
        }
        for (PlanningDataFreshnessScheduleEntity entity : entities) {
            result.add(toDto(entity));
        }
        return result;
    }

    private void fillDefaults(PlanningDataFreshnessScheduleEntity entity, Date now) {
        if (entity.getFailCount() == null) {
            entity.setFailCount(0);
        }
        if (entity.getEnabled() == null) {
            entity.setEnabled(DataFreshnessSchedulePolicy.isBackgroundEligible(entity.getPrepareType(), entity.getSessionStatus()));
        }
        int interval = DataFreshnessSchedulePolicy.calculateIntervalMinutes(
                entity.getSessionCreateTime(),
                entity.getLastAccessedAt(),
                entity.getSessionStatus(),
                now
        );
        entity.setCheckIntervalMinutes(Math.min(interval, DataFreshnessSchedulePolicy.MAX_INTERVAL_MINUTES));
        if (entity.getNextCheckAt() == null
                || (entity.getLastCheckedAt() != null && !entity.getNextCheckAt().after(entity.getLastCheckedAt()))) {
            entity.setNextCheckAt(DataFreshnessSchedulePolicy.calculateNextCheckAt(entity.getLastCheckedAt(), interval, now));
        }
        if (entity.getLastCheckStatus() == null) {
            entity.setLastCheckStatus("pending");
        }
    }

    private void merge(PlanningDataFreshnessScheduleEntity existing, PlanningDataFreshnessScheduleEntity incoming) {
        if (incoming.getTenantId() != null) existing.setTenantId(incoming.getTenantId());
        if (incoming.getPrepareType() != null) existing.setPrepareType(incoming.getPrepareType());
        if (incoming.getProvinceCode() != null) existing.setProvinceCode(incoming.getProvinceCode());
        if (incoming.getProvinceName() != null) existing.setProvinceName(incoming.getProvinceName());
        if (incoming.getExamYear() != null) existing.setExamYear(incoming.getExamYear());
        if (incoming.getSessionStatus() != null) existing.setSessionStatus(incoming.getSessionStatus());
        if (incoming.getSessionCreateTime() != null) existing.setSessionCreateTime(incoming.getSessionCreateTime());
        if (incoming.getLastAccessedAt() != null) existing.setLastAccessedAt(incoming.getLastAccessedAt());
        if (incoming.getLastCheckedAt() != null) existing.setLastCheckedAt(incoming.getLastCheckedAt());
        if (incoming.getNextCheckAt() != null) existing.setNextCheckAt(incoming.getNextCheckAt());
        if (incoming.getCheckIntervalMinutes() != null) existing.setCheckIntervalMinutes(incoming.getCheckIntervalMinutes());
        if (incoming.getLastCheckSource() != null) existing.setLastCheckSource(incoming.getLastCheckSource());
        if (incoming.getLastCheckStatus() != null) existing.setLastCheckStatus(incoming.getLastCheckStatus());
        if (incoming.getSourceDataHash() != null) existing.setSourceDataHash(incoming.getSourceDataHash());
        if (incoming.getLatestSourceDataHash() != null) existing.setLatestSourceDataHash(incoming.getLatestSourceDataHash());
        if (incoming.getFailCount() != null) existing.setFailCount(incoming.getFailCount());
        if (incoming.getLastError() != null) existing.setLastError(incoming.getLastError());
        if (incoming.getLastFailedAt() != null) existing.setLastFailedAt(incoming.getLastFailedAt());
        if (incoming.getEnabled() != null) existing.setEnabled(incoming.getEnabled());
    }

    private String format(Date date) {
        if (date == null) {
            return null;
        }
        return OffsetDateTime.ofInstant(date.toInstant(), ZoneId.systemDefault()).toString();
    }

    private String truncate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }
}
