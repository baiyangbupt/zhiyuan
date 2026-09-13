package com.ytell.zhiyuan.common.util;

import com.alibaba.fastjson.JSON;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * 响应内容指纹：把一次取数拿到的 <b>data 本身</b> 变成可比较的「数据版本」。
 *
 * <p>用途见 {@code EvidenceLedgerService}：证据失效判定要拿「这条记录当时取到的内容」
 * 跟「现在取到的内容」比。上游响应信封上的 {@code timestamp} 每次都变、{@code year} 是请求参数，
 * 都不能当版本；对内容本身算摘要是对齐本仓既有约定的做法
 * （{@code PlanningStateService} 用 {@code snapshot.getSourceDataHash()} 当数据版本，
 * {@code VolunteerSourceDataSyncService#buildDigest()} 用 SHA-256 十六进制串）。</p>
 *
 * <p>规范化规则固定为：<b>只取 data 子对象 → 对象键按字典序排序、值为 null 的键剔除 →
 * 数组保持上游给的顺序 → UTF-8 → SHA-256 → 取前 32 位十六进制</b>。</p>
 *
 * <p>与 {@link EvidenceParamsDigest} 有两处有意的差异，不要互相复用：
 * 它算的是<b>请求参数</b>，这里算的是<b>响应内容</b>；它对无序集合按规范值排序，
 * 这里对数组<b>保持原序</b>——数组顺序是数据的一部分，排序会抹掉真实变化。</p>
 *
 * <p>信封字段（{@code code} / {@code msg} / {@code timestamp} / {@code errorMsg} /
 * {@code isSuccess} / {@code path}）一个都不参与：{@code timestamp} 逐次调用都变，
 * 算进去会让所有证据立刻失效，等于没有证据机制。</p>
 */
public final class EvidenceContentDigest {

    private static final int DIGEST_HEX_LENGTH = 32;

    private EvidenceContentDigest() {
    }

    /**
     * 计算 data 的内容摘要。
     *
     * @param data 上游响应信封里的 data 子对象，可以是对象也可以是数组
     * @return 32 位十六进制摘要；{@code data} 为 null 或无法规范化时返回 {@code null}，
     * 调用方据此不签发证据（fail-closed，方向与「拿不到版本就不签发」一致）
     */
    public static String digest(Object data) {
        String canonical = canonical(data);
        if (canonical == null) {
            return null;
        }
        return sha256Hex(canonical).substring(0, DIGEST_HEX_LENGTH);
    }

    /** 规范形式，便于测试与排查；不参与存储。{@code data} 为 null 时返回 {@code null}。 */
    public static String canonical(Object data) {
        if (data == null) {
            return null;
        }
        try {
            Object json = JSON.toJSON(data);
            if (json == null) {
                return null;
            }
            StringBuilder builder = new StringBuilder();
            appendValue(builder, json);
            return builder.toString();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static void appendValue(StringBuilder builder, Object value) {
        if (value == null) {
            builder.append("null");
            return;
        }
        if (value instanceof Map) {
            appendObject(builder, (Map<?, ?>) value);
            return;
        }
        if (value instanceof Collection) {
            appendArray(builder, new ArrayList<Object>((Collection<?>) value));
            return;
        }
        if (value.getClass().isArray()) {
            int length = java.lang.reflect.Array.getLength(value);
            List<Object> items = new ArrayList<Object>(length);
            for (int i = 0; i < length; i++) {
                items.add(java.lang.reflect.Array.get(value, i));
            }
            appendArray(builder, items);
            return;
        }
        appendScalar(builder, value);
    }

    /** 对象：键按字典序，值为 null 的键剔除。 */
    private static void appendObject(StringBuilder builder, Map<?, ?> source) {
        Map<String, Object> sorted = new TreeMap<String, Object>();
        for (Map.Entry<?, ?> entry : source.entrySet()) {
            if (entry.getKey() == null || entry.getValue() == null) {
                continue;
            }
            sorted.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        builder.append('{');
        boolean first = true;
        for (Map.Entry<String, Object> entry : sorted.entrySet()) {
            if (!first) {
                builder.append(',');
            }
            first = false;
            appendString(builder, entry.getKey());
            builder.append(':');
            appendValue(builder, entry.getValue());
        }
        builder.append('}');
    }

    /** 数组：保持上游给的顺序，元素不排序也不剔除。 */
    private static void appendArray(StringBuilder builder, List<?> items) {
        builder.append('[');
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) {
                builder.append(',');
            }
            appendValue(builder, items.get(i));
        }
        builder.append(']');
    }

    private static void appendScalar(StringBuilder builder, Object value) {
        try {
            builder.append(JSON.toJSONString(value));
        } catch (RuntimeException e) {
            // 单个叶子序列化失败不应让整份数据算不出摘要：退化成 Java 的 toString。
            appendString(builder, String.valueOf(value));
        }
    }

    private static void appendString(StringBuilder builder, String value) {
        builder.append('"');
        for (int i = 0; i < value.length(); i++) {
            char current = value.charAt(i);
            switch (current) {
                case '"':
                    builder.append("\\\"");
                    break;
                case '\\':
                    builder.append("\\\\");
                    break;
                case '\n':
                    builder.append("\\n");
                    break;
                case '\r':
                    builder.append("\\r");
                    break;
                case '\t':
                    builder.append("\\t");
                    break;
                default:
                    if (current < 0x20) {
                        builder.append(String.format("\\u%04x", (int) current));
                    } else {
                        builder.append(current);
                    }
            }
        }
        builder.append('"');
    }

    private static String sha256Hex(String text) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(bytes.length * 2);
            for (byte item : bytes) {
                hex.append(Character.forDigit((item >> 4) & 0xF, 16));
                hex.append(Character.forDigit(item & 0xF, 16));
            }
            return hex.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 not available", e);
        }
    }
}
