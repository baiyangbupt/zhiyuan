package com.ytell.zhiyuan.service.shared;

import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ytell.zhiyuan.mapper.PendingConfirmationMapper;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class PendingConfirmationSharedService
        extends ServiceImpl<PendingConfirmationMapper, PendingConfirmationEntity> {

    private static final String STATUS_ACTIVE = "active";
    private static final String STATUS_APPLYING = "applying";
    private static final String STATUS_EXPIRED = "expired";
    private static final String RESOLVED_ACTION_EXPIRE = "expire";

    /**
     * 未决预览的存活时长（分钟）。默认 24 小时；<= 0 关闭 TTL，行为与旧版本一致。
     *
     * <p>只作用于 {@code active} 行。{@code applying} 行的租约/claim 语义必须保持不变，
     * 是否失败只能由 reconcile 依据 operation 台账判定，TTL 不能替它下结论。</p>
     */
    @Value("${planning.pending.ttl-minutes:1440}")
    private long pendingTtlMinutes = 1440L;

    /**
     * 读路径：先按 TTL 淘汰过期的 active 行，再返回当前行。
     *
     * <p>过期行不会被隐藏，而是以 {@code expired} 状态返回——写路径（upsert）靠
     * revision 接续替换它；冷加载的 lastProposal 也需要看到"已落定"的状态。</p>
     */
    public PendingConfirmationEntity getCurrent(Long tenantId, Long chatSessionId) {
        return expireIfStale(loadCurrent(tenantId, chatSessionId));
    }

    /**
     * J1 只读旅程用：只取真正的未决行（active/applying），按 revision 倒序。
     *
     * <p>不改 {@link #getCurrent} 的状态过滤：写路径（upsert/resolve）需要看到已解决行来维持
     * revision/CAS 语义；把状态过滤塞进 getCurrent 会改变写侧行为。这里只额外保证
     * "已过 TTL 的 active" 不再作为可确认的 pending 返回。</p>
     */
    public PendingConfirmationEntity getActiveOrApplying(Long tenantId, Long chatSessionId) {
        PendingConfirmationEntity current =
                expireIfStale(loadActiveOrApplying(tenantId, chatSessionId));
        if (current == null) {
            return null;
        }
        String status = current.getStatus();
        return STATUS_ACTIVE.equals(status) || STATUS_APPLYING.equals(status) ? current : null;
    }

    /**
     * reconcile 用：行锁内读取并顺带淘汰过期的 active 行。
     * 行已被本事务锁住，过期 CAS 不会与并发 claim 竞争；返回 expired 行让 reconcile
     * 如实报告 pendingStatus=expired（而不是假装"没有 pending"）。
     */
    public PendingConfirmationEntity lockCurrent(Long tenantId, Long chatSessionId) {
        return expireIfStale(loadCurrentForUpdate(tenantId, chatSessionId));
    }

    /**
     * TTL 核心：只把超过存活期且仍是 active 的行 CAS 成 expired。
     *
     * <p>CAS 同时比对 revision / pendingId / status=active：如果期间用户已确认（active→applying）
     * 或被新的 upsert 取代，更新会失败，此时重读真实行而不是拿旧快照下结论。
     * 成功后 revision+1，因此持有旧 revision 的确认请求会在 CAS 处失败。</p>
     */
    PendingConfirmationEntity expireIfStale(PendingConfirmationEntity current) {
        if (!isStaleActive(current)) {
            return current;
        }
        PendingConfirmationEntity expired = copyForExpiry(current);
        boolean updated = compareAndSet(
                expired, current.getRevision(), current.getPendingId(), STATUS_ACTIVE);
        if (updated) {
            return expired;
        }
        // 并发迁移赢了 CAS（例如刚被 claim 成 applying）：重读真实状态。
        PendingConfirmationEntity latest =
                loadCurrent(current.getTenantId(), current.getChatSessionId());
        return latest == null ? current : latest;
    }

    private boolean isStaleActive(PendingConfirmationEntity current) {
        if (current == null || !STATUS_ACTIVE.equals(current.getStatus())) {
            return false;
        }
        if (pendingTtlMinutes <= 0L || current.getRevision() == null) {
            return false;
        }
        Date anchor = current.getCreateTime() != null
                ? current.getCreateTime() : current.getUpdateTime();
        if (anchor == null) {
            return false;
        }
        return System.currentTimeMillis() - anchor.getTime() > pendingTtlMinutes * 60_000L;
    }

    private PendingConfirmationEntity copyForExpiry(PendingConfirmationEntity current) {
        long revision = current.getRevision() + 1L;
        PendingConfirmationEntity next = new PendingConfirmationEntity();
        next.setId(current.getId());
        next.setTenantId(current.getTenantId());
        next.setChatSessionId(current.getChatSessionId());
        next.setPendingId(current.getPendingId());
        next.setRevision(revision);
        next.setKind(current.getKind());
        next.setActionFamily(current.getActionFamily());
        next.setStatus(STATUS_EXPIRED);
        next.setClaimToken(current.getClaimToken());
        next.setClaimExpiresAt(null);
        next.setDataValue(expiredDataValue(current.getDataValue(), revision));
        next.setResultCode(current.getResultCode());
        next.setResolvedAction(RESOLVED_ACTION_EXPIRE);
        return next;
    }

    /** 快照里的 status/revision 与列保持一致（与 resolve/reconcile 的迁移写法相同）。 */
    private String expiredDataValue(String dataValue, long revision) {
        if (dataValue == null || dataValue.trim().isEmpty()) {
            return dataValue;
        }
        try {
            Map<String, Object> payload = JSONObject.parseObject(dataValue, Map.class);
            if (payload == null) {
                payload = new LinkedHashMap<String, Object>();
            }
            payload.put("status", STATUS_EXPIRED);
            payload.put("revision", revision);
            return JSONObject.toJSONString(payload);
        } catch (RuntimeException ex) {
            // 快照 JSON 异常不应阻断过期迁移；顶层 status 才是权威。
            return dataValue;
        }
    }

    private PendingConfirmationEntity loadCurrent(Long tenantId, Long chatSessionId) {
        QueryWrapper<PendingConfirmationEntity> query = new QueryWrapper<PendingConfirmationEntity>();
        query.lambda()
                .eq(PendingConfirmationEntity::getTenantId, tenantId)
                .eq(PendingConfirmationEntity::getChatSessionId, chatSessionId)
                .last("limit 1");
        return this.getOne(query);
    }

    private PendingConfirmationEntity loadActiveOrApplying(Long tenantId, Long chatSessionId) {
        QueryWrapper<PendingConfirmationEntity> query = new QueryWrapper<PendingConfirmationEntity>();
        query.lambda()
                .eq(PendingConfirmationEntity::getTenantId, tenantId)
                .eq(PendingConfirmationEntity::getChatSessionId, chatSessionId)
                .in(PendingConfirmationEntity::getStatus, STATUS_ACTIVE, STATUS_APPLYING)
                .orderByDesc(PendingConfirmationEntity::getRevision)
                .last("limit 1");
        return this.getOne(query);
    }

    private PendingConfirmationEntity loadCurrentForUpdate(Long tenantId, Long chatSessionId) {
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
        // 这里对标整行覆写语义，null 也真正落库。所有调用方（upsert/resolve/过期）都构造完整实体，安全。
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
