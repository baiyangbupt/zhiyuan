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
        // 整行逐列显式赋值（含 null）：MyBatis-Plus 默认 NOT_NULL 更新策略会静默跳过 null 字段，
        // 造成“已确认成功/取消的行仍带旧 claimToken、旧 resultCode（如 84009）”等残留；
        // 这里对标整行覆写语义，null 也真正落库。两个调用方（upsert/resolve）都构造完整实体，安全。
        update.lambda()
                .set(PendingConfirmationEntity::getPendingId, next.getPendingId())
                .set(PendingConfirmationEntity::getRevision, next.getRevision())
                .set(PendingConfirmationEntity::getKind, next.getKind())
                .set(PendingConfirmationEntity::getActionFamily, next.getActionFamily())
                .set(PendingConfirmationEntity::getStatus, next.getStatus())
                .set(PendingConfirmationEntity::getClaimToken, next.getClaimToken())
                .set(PendingConfirmationEntity::getClaimExpiresAt, next.getClaimExpiresAt())
                .set(PendingConfirmationEntity::getDataValue, next.getDataValue())
                .set(PendingConfirmationEntity::getResultCode, next.getResultCode())
                .set(PendingConfirmationEntity::getResolvedAction, next.getResolvedAction());
        return this.update(null, update);
    }
}
