package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ytell.zhiyuan.mapper.PendingConfirmationMapper;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import org.springframework.stereotype.Service;

@Service
public class PendingConfirmationSharedService
        extends ServiceImpl<PendingConfirmationMapper, PendingConfirmationEntity> {

    public PendingConfirmationEntity getCurrent(Long tenantId, Long chatSessionId) {
        QueryWrapper<PendingConfirmationEntity> query = new QueryWrapper<PendingConfirmationEntity>();
        query.lambda()
                .eq(PendingConfirmationEntity::getTenantId, tenantId)
                .eq(PendingConfirmationEntity::getChatSessionId, chatSessionId)
                .last("limit 1");
        return this.getOne(query);
    }

    public PendingConfirmationEntity lockCurrent(Long tenantId, Long chatSessionId) {
        QueryWrapper<PendingConfirmationEntity> query = new QueryWrapper<PendingConfirmationEntity>();
        query.lambda()
                .eq(PendingConfirmationEntity::getTenantId, tenantId)
                .eq(PendingConfirmationEntity::getChatSessionId, chatSessionId)
                .last("limit 1 for update");
        return this.getOne(query);
    }

    public boolean compareAndSet(PendingConfirmationEntity next, long expectedRevision,
                                 String expectedPendingId, String expectedStatus) {
        UpdateWrapper<PendingConfirmationEntity> update = new UpdateWrapper<PendingConfirmationEntity>();
        update.lambda()
                .eq(PendingConfirmationEntity::getTenantId, next.getTenantId())
                .eq(PendingConfirmationEntity::getChatSessionId, next.getChatSessionId())
                .eq(PendingConfirmationEntity::getRevision, expectedRevision);
        if (expectedPendingId != null) {
            update.lambda().eq(PendingConfirmationEntity::getPendingId, expectedPendingId);
        }
        if (expectedStatus != null) {
            update.lambda().eq(PendingConfirmationEntity::getStatus, expectedStatus);
        }
        return this.update(next, update);
    }
}
