package com.ytell.zhiyuan.common.util;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * 查询参数指纹：让「同一个问题又问了一遍」可判定。
 *
 * <p>规范化规则固定为：<b>键按字典序排序 → 值转字符串 → 空值与缺失键一律剔除 → UTF-8 → SHA-256
 * → 取前 32 位十六进制</b>。规则一旦固定不得更改，否则同一查询会算出不同摘要。</p>
 *
 * <p>实现细节：规范形式是一个 JSON 对象，键按字典序，值全部是字符串（嵌套结构除外）。
 * 值转字符串意味着 {@code 2025} 与 {@code "2025"} 得到同一个摘要，避免调用方类型差异造成假不一致。
 * 剔除规则：{@code null}、去空白后为空的字符串、空集合、空 Map、长度为 0 的数组。</p>
 */
public final class EvidenceParamsDigest {

    private static final int DIGEST_HEX_LENGTH = 32;

    private EvidenceParamsDigest() {
    }

    public static String digest(Map<String, ?> params) {
        return sha256Hex(canonical(params)).substring(0, DIGEST_HEX_LENGTH);
    }

    /** 规范形式，便于测试与排查；不参与存储。 */
    public static String canonical(Map<String, ?> params) {
        StringBuilder builder = new StringBuilder();
        appendObject(builder, params);
        return builder.toString();
    }

    /** 值是否属于「空」，空值在规范化时被剔除。 */
    public static boolean isEmptyValue(Object value) {
        if (value == null) {
            return true;
        }
        if (value instanceof CharSequence) {
            return value.toString().trim().isEmpty();
        }
        if (value instanceof Collection) {
            return ((Collection<?>) value).isEmpty();
        }
        if (value instanceof Map) {
            return ((Map<?, ?>) value).isEmpty();
        }
        if (value.getClass().isArray()) {
            return java.lang.reflect.Array.getLength(value) == 0;
        }
        return false;
    }

    private static void appendObject(StringBuilder builder, Map<?, ?> source) {
        builder.append('{');
        if (source != null) {
            Map<String, Object> sorted = new TreeMap<String, Object>();
            for (Map.Entry<?, ?> entry : source.entrySet()) {
                if (entry.getKey() == null) {
                    continue;
                }
                if (isEmptyValue(entry.getValue())) {
                    continue;
                }
                sorted.put(String.valueOf(entry.getKey()), entry.getValue());
            }
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
        }
        builder.append('}');
    }

    private static void appendValue(StringBuilder builder, Object value) {
        if (value instanceof Map) {
            appendObject(builder, (Map<?, ?>) value);
            return;
        }
        if (value instanceof Collection) {
            Collection<?> collection = (Collection<?>) value;
            List<String> items = new ArrayList<String>();
            for (Object item : collection) {
                if (isEmptyValue(item)) {
                    continue;
                }
                StringBuilder itemBuilder = new StringBuilder();
                appendValue(itemBuilder, item);
                items.add(itemBuilder.toString());
            }
            // 无序集合按规范值排序，保证集合类型实现差异不会改变摘要
            if (!(collection instanceof List)) {
                items.sort(Comparator.naturalOrder());
            }
            builder.append('[');
            for (int i = 0; i < items.size(); i++) {
                if (i > 0) {
                    builder.append(',');
                }
                builder.append(items.get(i));
            }
            builder.append(']');
            return;
        }
        if (value != null && value.getClass().isArray()) {
            int length = java.lang.reflect.Array.getLength(value);
            List<Object> items = new ArrayList<Object>(length);
            for (int i = 0; i < length; i++) {
                items.add(java.lang.reflect.Array.get(value, i));
            }
            appendValue(builder, items);
            return;
        }
        appendString(builder, String.valueOf(value));
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
