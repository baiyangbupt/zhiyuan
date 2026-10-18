package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * 评价版本与缓存键（J5.0）。
 *
 * <p>`evaluatedStateVersion` 必须进 `evaluationVersion`：否则旧 findings 会被
 * 当前 stateVersion 认证成“新”。任何 probe/权重/目标层级变化都要 bump
 * `EvaluationProbeRegistry.VERSION` 或这里的编译器/权重版本。</p>
 */
public final class EvaluationVersion {

    public static final String OBJECTIVE_COMPILER_VERSION = "objective-compiler-v1";
    public static final String OBJECTIVE_WEIGHTS_VERSION = "objective-weights-v1";

    private EvaluationVersion() {
    }

    public static String objectiveModelVersion() {
        return sha256("probeRegistry=" + EvaluationProbeRegistry.VERSION
                + "|compiler=" + OBJECTIVE_COMPILER_VERSION
                + "|weights=" + OBJECTIVE_WEIGHTS_VERSION);
    }

    /**
     * 缺 evaluatedStateVersion / planContentDigest / objectiveModelVersion 时返回 null：
     * 不建立“部分评价”的缓存，避免用半份输入认证旧结论。
     */
    public static String evaluationVersion(Integer evaluatedStateVersion,
                                           String planContentDigest,
                                           Integer candidateSourceVersion,
                                           String dataVersion,
                                           String objectiveModelVersion) {
        if (evaluatedStateVersion == null
                || Strings.isNullOrEmpty(planContentDigest)
                || Strings.isNullOrEmpty(objectiveModelVersion)) {
            return null;
        }
        return sha256("evaluatedStateVersion=" + evaluatedStateVersion
                + "|planContentDigest=" + planContentDigest
                + "|candidateSourceVersion=" + valueOrNone(candidateSourceVersion)
                + "|dataVersion=" + valueOrNone(dataVersion)
                + "|objectiveModelVersion=" + objectiveModelVersion);
    }

    public static String cacheKey(String tenantId, String sessionId, String evaluationVersion,
                                  String overlay, String counterfactual) {
        if (Strings.isNullOrEmpty(evaluationVersion)) {
            return null;
        }
        return "plan-evaluation:" + valueOrNone(tenantId) + ":" + valueOrNone(sessionId)
                + ":" + evaluationVersion
                + ":overlay=" + valueOrNone(overlay)
                + ":counterfactual=" + valueOrNone(counterfactual);
    }

    public static String sha256(String text) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(String.valueOf(text).getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(bytes.length * 2);
            for (byte value : bytes) {
                builder.append(String.format("%02x", value));
            }
            return builder.toString();
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 not available", error);
        }
    }

    private static String valueOrNone(Object value) {
        return value == null || "".equals(value) ? "none" : String.valueOf(value);
    }
}
