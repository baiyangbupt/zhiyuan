package com.ytell.zhiyuan.service.biz;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.ytell.zhiyuan.mapper.CodexThreadBindingMapper;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingReq;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingContextRes;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingResolveReq;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingRes;
import com.ytell.zhiyuan.model.entity.biz.CodexThreadBindingEntity;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class CodexThreadBindingService {

    @Autowired
    private CodexThreadBindingMapper bindingMapper;

    public String register(Long tenantId, CodexThreadBindingReq req) {
        validate(tenantId, req);
        String threadId = req.getThreadId().trim();
        String handleHash = hashHandle(req.getHandle());
        QueryWrapper<CodexThreadBindingEntity> duplicateThread = new QueryWrapper<CodexThreadBindingEntity>();
        duplicateThread.lambda()
                .eq(CodexThreadBindingEntity::getTenantId, tenantId)
                .eq(CodexThreadBindingEntity::getThreadId, threadId);
        CodexThreadBindingEntity existing = bindingMapper.selectOne(duplicateThread);
        if (existing != null) {
            if (!req.getChatSessionId().equals(existing.getChatSessionId())
                    || !req.getUserId().equals(existing.getUserId())) {
                throw new IllegalStateException("binding_thread_identity_conflict");
            }
            existing.setHandleHash(handleHash);
            existing.setAllowedCapabilities(String.join(",", req.getAllowedCapabilities()));
            existing.setExpiresAt(parseExpiry(req.getExpiresAt()));
            existing.setRevokedAt(null);
            existing.setUpdateTime(new Date());
            bindingMapper.updateById(existing);
            return existing.getHandleHash();
        }
        QueryWrapper<CodexThreadBindingEntity> duplicateHandle = new QueryWrapper<CodexThreadBindingEntity>();
        duplicateHandle.lambda().eq(CodexThreadBindingEntity::getHandleHash, handleHash);
        if (bindingMapper.selectOne(duplicateHandle) != null) {
            throw new IllegalStateException("binding_handle_exists");
        }
        CodexThreadBindingEntity entity = new CodexThreadBindingEntity();
        entity.setTenantId(tenantId);
        entity.setChatSessionId(req.getChatSessionId());
        entity.setUserId(req.getUserId());
        entity.setThreadId(threadId);
        entity.setHandleHash(handleHash);
        entity.setAllowedCapabilities(String.join(",", req.getAllowedCapabilities()));
        entity.setExpiresAt(parseExpiry(req.getExpiresAt()));
        entity.setCreateTime(new Date());
        entity.setUpdateTime(new Date());
        bindingMapper.insert(entity);
        return entity.getHandleHash();
    }

    public CodexThreadBindingRes registerResponse(Long tenantId, CodexThreadBindingReq req) {
        register(tenantId, req);
        CodexThreadBindingRes response = new CodexThreadBindingRes();
        response.setThreadId(req.getThreadId().trim());
        response.setHandle(req.getHandle());
        response.setAllowedCapabilities(req.getAllowedCapabilities());
        response.setExpiresAt(req.getExpiresAt());
        return response;
    }

    public CodexThreadBindingEntity resolve(Long tenantId,
                                            Long chatSessionId,
                                            String threadId,
                                            String handle,
                                            String capability) {
        if (tenantId == null || chatSessionId == null || isBlank(threadId) || isBlank(handle)) {
            throw new IllegalArgumentException("binding identity is required");
        }
        QueryWrapper<CodexThreadBindingEntity> query = new QueryWrapper<CodexThreadBindingEntity>();
        query.lambda()
                .eq(CodexThreadBindingEntity::getTenantId, tenantId)
                .eq(CodexThreadBindingEntity::getChatSessionId, chatSessionId)
                .eq(CodexThreadBindingEntity::getThreadId, threadId.trim())
                .eq(CodexThreadBindingEntity::getHandleHash, hashHandle(handle));
        CodexThreadBindingEntity entity = bindingMapper.selectOne(query);
        if (entity == null) {
            throw new IllegalStateException("binding_not_found");
        }
        if (entity.getRevokedAt() != null) {
            throw new IllegalStateException("binding_revoked");
        }
        if (entity.getExpiresAt() == null || !entity.getExpiresAt().after(new Date())) {
            throw new IllegalStateException("binding_expired");
        }
        List<String> capabilities = splitCapabilities(entity.getAllowedCapabilities());
        if (!capabilities.contains(capability)) {
            throw new IllegalStateException("capability_denied");
        }
        return entity;
    }

    public CodexThreadBindingContextRes resolveResponse(Long tenantId,
                                                        CodexThreadBindingResolveReq req) {
        if (req == null) {
            throw new IllegalArgumentException("binding resolve request is required");
        }
        CodexThreadBindingEntity entity = resolve(
                tenantId,
                req.getChatSessionId(),
                req.getThreadId(),
                req.getHandle(),
                req.getCapability());
        return toContext(entity);
    }

    private CodexThreadBindingContextRes toContext(CodexThreadBindingEntity entity) {
        CodexThreadBindingContextRes response = new CodexThreadBindingContextRes();
        response.setTenantId(entity.getTenantId());
        response.setChatSessionId(entity.getChatSessionId());
        response.setUserId(entity.getUserId());
        response.setThreadId(entity.getThreadId());
        response.setAllowedCapabilities(splitCapabilities(entity.getAllowedCapabilities()));
        response.setExpiresAt(DateTimeFormatter.ISO_INSTANT.format(entity.getExpiresAt().toInstant()));
        return response;
    }

    /**
     * 查该 (租户, 会话) 当前有效的绑定；没有则返回 {@code null}。
     *
     * <p>与 {@link #resolve} 的分工：resolve 要 handle，证明"我就是当初注册的那个人"，
     * 用于工具调用时的身份核验；这条不需要 handle——它的用途恰恰是在 handle
     * 已经随进程重启丢掉之后，把 thread 找回来。所以它**只对认证过的内部
     * 调用方开放**，不对外。</p>
     *
     * <p>返回 null 表示"没有绑定"（可以新建），异常表示"查不了"（不许新建）——
     * 调用方必须区分这两者，把查询失败当成没有绑定，等于用一次后端故障
     * 换掉用户的上下文。</p>
     */
    public CodexThreadBindingContextRes current(Long tenantId, Long chatSessionId) {
        if (tenantId == null || chatSessionId == null) {
            throw new IllegalArgumentException("tenant and chatSession are required");
        }
        CodexThreadBindingEntity entity = bindingMapper.selectCurrent(tenantId, chatSessionId, new Date());
        if (entity == null) {
            return null;
        }
        return toContext(entity);
    }

    public void revoke(Long tenantId, String threadId) {
        if (tenantId == null || isBlank(threadId)) {
            throw new IllegalArgumentException("tenantId and threadId are required");
        }
        UpdateWrapper<CodexThreadBindingEntity> update = new UpdateWrapper<CodexThreadBindingEntity>();
        update.lambda()
                .eq(CodexThreadBindingEntity::getTenantId, tenantId)
                .eq(CodexThreadBindingEntity::getThreadId, threadId.trim());
        CodexThreadBindingEntity next = new CodexThreadBindingEntity();
        next.setRevokedAt(new Date());
        next.setUpdateTime(new Date());
        bindingMapper.update(next, update);
    }

    public String hashHandle(String handle) {
        if (isBlank(handle)) {
            throw new IllegalArgumentException("handle is required");
        }
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(handle.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(digest.length * 2);
            for (byte value : digest) {
                result.append(String.format("%02x", value));
            }
            return result.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }

    private void validate(Long tenantId, CodexThreadBindingReq req) {
        if (tenantId == null || req == null || req.getChatSessionId() == null || req.getUserId() == null
                || isBlank(req.getThreadId()) || isBlank(req.getHandle())) {
            throw new IllegalArgumentException("tenant, session, user, thread and handle are required");
        }
        if (req.getAllowedCapabilities() == null || req.getAllowedCapabilities().isEmpty()) {
            throw new IllegalArgumentException("allowedCapabilities is required");
        }
        parseExpiry(req.getExpiresAt());
    }

    private Date parseExpiry(String value) {
        if (isBlank(value)) {
            throw new IllegalArgumentException("expiresAt is required");
        }
        try {
            Date expiry = Date.from(OffsetDateTime.parse(value.trim()).toInstant());
            if (!expiry.after(new Date())) {
                throw new IllegalArgumentException("expiresAt must be in the future");
            }
            return expiry;
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException("expiresAt must be ISO-8601", e);
        }
    }

    private List<String> splitCapabilities(String value) {
        if (isBlank(value)) {
            return Arrays.asList();
        }
        return Arrays.stream(value.split(","))
                .map(String::trim)
                .filter(item -> !item.isEmpty())
                .collect(Collectors.toList());
    }

    private boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
