package com.ytell.zhiyuan.model.dto;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import lombok.Getter;

import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * score-update 的实际补丁字段集。
 *
 * <p>关键点：不能先把 HTTP body 绑成带默认值的 {@link CreateSessionReq} 再反推“用户带了
 * 哪些字段”——`filterType` 默认 `2` 就是这么把存量 `3` 静默覆盖掉的。这里保留原始
 * JSON 白名单，只让真正出现且非 null 的字段参与合并。</p>
 */
@Getter
public class ScoreUpdatePatch {

    /** 成绩/资格补录允许触碰的字段；模式、专业筛选、志愿数等不在其中。 */
    private static final Set<String> ALLOWED_FIELDS = new LinkedHashSet<String>(Arrays.asList(
            "province", "subjectType", "prepareType", "batch", "totalScore", "totalScorePos",
            "examYear", "subjectScoreList", "subjectList", "specialPlan"));

    private final JSONObject raw;
    private final CreateSessionReq value;
    /** 网关基于已持久化用户消息注入的来源，不进入成绩真相。 */
    private final Long sourceMessageId;
    private final String sourceTurnId;
    private final Integer sourceVersionGuard;

    private ScoreUpdatePatch(JSONObject raw, Long sourceMessageId, String sourceTurnId,
                             Integer sourceVersionGuard) {
        this.raw = raw;
        this.value = JSON.parseObject(raw.toJSONString(), CreateSessionReq.class);
        this.sourceMessageId = sourceMessageId;
        this.sourceTurnId = sourceTurnId;
        this.sourceVersionGuard = sourceVersionGuard;
    }

    public static ScoreUpdatePatch fromRaw(Map<String, Object> body) {
        JSONObject raw = new JSONObject(true);
        if (body != null) {
            for (String key : ALLOWED_FIELDS) {
                Object value = body.get(key);
                if (value == null) {
                    continue;
                }
                if (value instanceof String && ((String) value).trim().isEmpty()) {
                    continue;
                }
                raw.put(key, value);
            }
        }
        Object specialPlan = raw.get("specialPlan");
        if (specialPlan != null && !(specialPlan instanceof Boolean)) {
            throw new BusinessException(110, "专项资格必须明确回答“有”或“没有”");
        }
        return new ScoreUpdatePatch(raw,
                sourceMessageId(body == null ? null : body.get("sourceMessageId")),
                sourceText(body == null ? null : body.get("sourceTurnId")),
                sourceVersionGuard(body == null ? null : body.get("sourceVersionGuard")));
    }

    private static Integer sourceVersionGuard(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        try {
            if (!text.matches("[0-9]+")) {
                throw new NumberFormatException();
            }
            return Integer.valueOf(text);
        } catch (NumberFormatException ex) {
            throw new BusinessException(110, "成绩更新来源版本必须为非负整数");
        }
    }

    private static Long sourceMessageId(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        String text = String.valueOf(value).trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return Long.valueOf(text);
        } catch (NumberFormatException ex) {
            throw new BusinessException(110, "来源消息编号无法识别");
        }
    }

    private static String sourceText(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    /** 兼容非 HTTP 的旧调用；只把 DTO 里非空字段当补丁，仍不推断默认值。 */
    public static ScoreUpdatePatch fromDto(CreateSessionReq req) {
        if (req == null) {
            return fromRaw(null);
        }
        JSONObject dto = (JSONObject) JSON.toJSON(req);
        JSONObject raw = new JSONObject(true);
        for (String key : ALLOWED_FIELDS) {
            Object value = dto.get(key);
            if (value == null) {
                continue;
            }
            if (value instanceof java.util.Collection && ((java.util.Collection<?>) value).isEmpty()) {
                continue;
            }
            raw.put(key, value);
        }
        return new ScoreUpdatePatch(raw, null, null, null);
    }

    public boolean isEmpty() {
        return raw.isEmpty();
    }

    public boolean has(String field) {
        return raw.containsKey(field);
    }

    public String canonicalJson() {
        return raw.toJSONString();
    }
}
