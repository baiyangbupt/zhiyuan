package com.ytell.zhiyuan.common.util;

import java.security.SecureRandom;

/**
 * ULID 生成器：48 位毫秒时间戳 + 80 位随机数，Crockford Base32 编码，固定 26 字符。
 *
 * <p>选 ULID 而不是自增或参数哈希，理由有两条：时间有序便于按会话分页和 TTL 清理；
 * 不可预测使调用方无法拼出一个"看起来对"的 ID 去碰运气。</p>
 */
public final class Ulid {

    private static final char[] ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ".toCharArray();
    private static final int TIME_CHARS = 10;
    private static final int RANDOM_CHARS = 16;
    private static final SecureRandom RANDOM = new SecureRandom();

    private Ulid() {
    }

    public static String next() {
        long timestamp = System.currentTimeMillis();
        char[] value = new char[TIME_CHARS + RANDOM_CHARS];
        for (int i = TIME_CHARS - 1; i >= 0; i--) {
            value[i] = ENCODING[(int) (timestamp & 0x1F)];
            timestamp >>>= 5;
        }
        for (int i = TIME_CHARS; i < value.length; i++) {
            value[i] = ENCODING[RANDOM.nextInt(ENCODING.length)];
        }
        return new String(value);
    }
}
