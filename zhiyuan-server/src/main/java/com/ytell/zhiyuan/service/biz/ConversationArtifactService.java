package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.alibaba.fastjson.serializer.SerializerFeature;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.ConversationArtifactMapper;
import com.ytell.zhiyuan.model.dto.planning.ArtifactDTO;
import com.ytell.zhiyuan.model.dto.planning.ArtifactPageDTO;
import com.ytell.zhiyuan.model.entity.biz.ConversationArtifactEntity;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 会话产物存储：候选表、对比矩阵、冻结方案这类"很大但只需给模型一个引用"的对象。
 *
 * <p>为什么必须落库而不是放进程内存：产物是**跨回合**被引用的。用户在第 3 轮
 * 生成的候选表，可能在第 7 轮拿来对比；进程重启或换一个 worker，内存里那份就没了，
 * 而模型手上还拿着 artifactId。引用一个不存在的产物比没有引用更糟——它会让模型
 * 以为自己有数据。
 *
 * <p>产物**不可原地修改**：内容与摘要一起写入，读取时复核摘要。上游若改了数据，
 * 做法是生成一个新产物，而不是改旧的那份——否则同一个 artifactId 在不同时刻
 * 代表不同内容，引用它的所有结论都要重新判断。
 */
@Service
public class ConversationArtifactService {

    /** 单个产物上限。再大就该分页，而不是让一次读取把内存和链路撑爆。 */
    public static final int MAX_PAYLOAD_BYTES = 2 * 1024 * 1024;
    public static final int DEFAULT_PAGE_SIZE = 20;
    public static final int MAX_PAGE_SIZE = 50;

    @Autowired
    private ConversationArtifactMapper artifactMapper;

    public String put(Long tenantId, Long chatSessionId, String kind,
                      Object payload, Map<String, Object> dependencies, Date expiresAt) {
        if (tenantId == null || chatSessionId == null) {
            throw new BusinessException(400, "artifact_scope_required");
        }
        if (kind == null || kind.trim().isEmpty()) {
            throw new BusinessException(400, "artifact_kind_required");
        }
        if (expiresAt == null) {
            // 没有有效期的产物会永久留在库里，而它引用的画像/工作区版本早就变了。
            throw new BusinessException(400, "artifact_expiry_required");
        }
        String payloadJson = canonicalJson(payload);
        if (payloadJson.getBytes(StandardCharsets.UTF_8).length > MAX_PAYLOAD_BYTES) {
            // 不截断：截断后的 JSON 既不是原产物，也无法被解析。
            throw new BusinessException(413, "artifact_payload_too_large");
        }

        ConversationArtifactEntity entity = new ConversationArtifactEntity();
        entity.setArtifactId("art_" + UUID.randomUUID().toString().replace("-", ""));
        entity.setTenantId(tenantId);
        entity.setChatSessionId(chatSessionId);
        entity.setKind(kind);
        entity.setPayloadJson(payloadJson);
        entity.setPayloadDigest(digest(payloadJson));
        entity.setDependenciesJson(canonicalJson(dependencies == null ? new JSONObject() : dependencies));
        entity.setExpiresAt(expiresAt);
        artifactMapper.insert(entity);
        return entity.getArtifactId();
    }

    public ArtifactDTO getOwned(Long tenantId, Long chatSessionId, String artifactId) {
        ConversationArtifactEntity entity = requireOwned(tenantId, chatSessionId, artifactId);
        requireFresh(entity);
        ArtifactDTO dto = new ArtifactDTO();
        dto.setArtifactId(entity.getArtifactId());
        dto.setKind(entity.getKind());
        dto.setPayload(JSON.parseObject(entity.getPayloadJson()));
        dto.setDependencies(JSON.parseObject(entity.getDependenciesJson()));
        dto.setPayloadDigest(entity.getPayloadDigest());
        dto.setExpiresAt(entity.getExpiresAt());
        dto.setCreatedAt(entity.getCreateTime());
        return dto;
    }

    /**
     * 分页读取产物内容。**只在后台读**：完整候选表可能有几百行，
     * 直接塞进模型上下文会把预算一次性吃光。
     */
    public ArtifactPageDTO pageOwned(Long tenantId, Long chatSessionId, String artifactId,
                                     String cursor, Integer limit) {
        ConversationArtifactEntity entity = requireOwned(tenantId, chatSessionId, artifactId);
        requireFresh(entity);
        int size = limit == null || limit <= 0 ? DEFAULT_PAGE_SIZE : Math.min(limit, MAX_PAGE_SIZE);
        int offset = parseCursor(cursor);

        JSONArray items = extractItems(entity.getPayloadJson());
        List<Map<String, Object>> page = new ArrayList<>();
        for (int index = offset; index < items.size() && page.size() < size; index++) {
            page.add(items.getJSONObject(index));
        }

        ArtifactPageDTO dto = new ArtifactPageDTO();
        dto.setArtifactId(entity.getArtifactId());
        dto.setKind(entity.getKind());
        dto.setItems(page);
        dto.setTotal(items.size());
        dto.setPayloadDigest(entity.getPayloadDigest());
        int next = offset + page.size();
        dto.setNextCursor(next < items.size() ? String.valueOf(next) : null);
        return dto;
    }

    private JSONArray extractItems(String payloadJson) {
        JSONObject payload = JSON.parseObject(payloadJson);
        if (payload == null) {
            return new JSONArray();
        }
        JSONArray items = payload.getJSONArray("items");
        return items == null ? new JSONArray() : items;
    }

    private int parseCursor(String cursor) {
        if (cursor == null || cursor.trim().isEmpty()) {
            return 0;
        }
        try {
            int value = Integer.parseInt(cursor.trim());
            if (value < 0) {
                throw new NumberFormatException("negative");
            }
            return value;
        } catch (NumberFormatException ex) {
            throw new BusinessException(400, "artifact_cursor_invalid");
        }
    }

    /**
     * 归属检查先于一切。
     *
     * <p>查不到与不属于自己都回同一个错误：区分开来就等于告诉调用方
     * "这个 id 是存在的，只是不是你的"——那是一次越权探测的确认信号。
     */
    private ConversationArtifactEntity requireOwned(Long tenantId, Long chatSessionId, String artifactId) {
        if (artifactId == null || artifactId.trim().isEmpty()) {
            throw new BusinessException(400, "artifact_id_required");
        }
        QueryWrapper<ConversationArtifactEntity> query = new QueryWrapper<>();
        query.eq("artifact_id", artifactId);
        query.eq("tenant_id", tenantId);
        query.eq("chat_session_id", chatSessionId);
        ConversationArtifactEntity entity = artifactMapper.selectOne(query);
        if (entity == null) {
            throw new BusinessException(404, "artifact_not_found");
        }
        return entity;
    }

    private void requireFresh(ConversationArtifactEntity entity) {
        if (entity.getExpiresAt() != null && entity.getExpiresAt().before(new Date())) {
            throw new BusinessException(410, "artifact_expired");
        }
        String recomputed = digest(entity.getPayloadJson());
        if (!recomputed.equals(entity.getPayloadDigest())) {
            // 内容与签名对不上：要么被改过、要么写入时就算错了。
            // 两种情况下都不能把它当可信内容交出去。
            throw new BusinessException(500, "artifact_digest_mismatch");
        }
    }

    /**
     * 稳定序列化：键按字典序、不输出 null。
     *
     * <p>摘要必须只取决于内容本身。FastJSON 默认按字段插入顺序输出，
     * 同一份数据换个构造路径就会得到不同字节、不同摘要——而那会被下游
     * 当成"内容变了"。
     */
    public static String canonicalJson(Object value) {
        return JSON.toJSONString(value,
                SerializerFeature.MapSortField,
                SerializerFeature.SortField);
    }

    public static String digest(String canonical) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(canonical.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(bytes.length * 2);
            for (byte value : bytes) {
                builder.append(Character.forDigit((value >> 4) & 0xF, 16));
                builder.append(Character.forDigit(value & 0xF, 16));
            }
            return builder.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 unavailable", ex);
        }
    }
}
