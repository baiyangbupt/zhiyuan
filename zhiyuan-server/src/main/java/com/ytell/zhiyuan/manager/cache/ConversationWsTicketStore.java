package com.ytell.zhiyuan.manager.cache;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.model.dto.conversation.TicketIdentity;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Collections;

/**
 * 对话 WebSocket 的一次性票据。
 *
 * <p>为什么浏览器不直接用登录态连 WS：WebSocket 的握手报文里带不上自定义头，
 * 而把长期凭证放在 URL 查询串上会进浏览器历史、代理日志和 HAR——
 * 那些地方都能被第三方看到。所以改成"先换一张 60 秒、一次性、绑定 Origin 的票"。
 *
 * <p>四条边界：
 * <ul>
 *   <li><b>只存哈希。</b> Redis 里存的是 SHA-256(ticket)，票据本身不落库——
 *       库被读到也不能拿去连。</li>
 *   <li><b>原子消费。</b> GET + DEL 走一段 Lua：分成两次调用会出现
 *       "两个连接同时读到同一张票"的窗口。</li>
 *   <li><b>绑定 Origin。</b> 票据只在签发时认定的来源可用，不做通配。</li>
 *   <li><b>不承载身份。</b> 票里没有用户可改的身份字段，身份由服务端查
 *       ChatSession 得到。</li>
 * </ul>
 */
@Slf4j
@Service
public class ConversationWsTicketStore {

    /** 票据有效期。够走完一次握手，不够被慢慢猜。 */
    public static final int TTL_SECONDS = 60;

    private static final String KEY_PREFIX = "conv:ws-ticket:";

    /** GET + DEL 必须原子：拆成两次会出现"两个连接同时拿到同一张票"的窗口。 */
    private static final DefaultRedisScript<String> CONSUME_SCRIPT = new DefaultRedisScript<String>(
            "local v = redis.call('GET', KEYS[1]) "
                    + "if v then redis.call('DEL', KEYS[1]) end "
                    + "return v",
            String.class);

    private static final SecureRandom RANDOM = new SecureRandom();

    @Autowired
    private StringRedisTemplate redisTemplate;

    /** 签发票据，返回**明文票据**——它只在这一次响应里出现，之后只剩哈希。 */
    public String issue(TicketIdentity identity) {
        if (identity == null) {
            throw new IllegalArgumentException("ticket_identity_required");
        }
        byte[] raw = new byte[32];
        RANDOM.nextBytes(raw);
        String ticket = Base64.getUrlEncoder().withoutPadding().encodeToString(raw);
        JSONObject payload = new JSONObject();
        payload.put("tenantId", identity.getTenantId());
        payload.put("sessionId", identity.getSessionId());
        payload.put("userId", identity.getUserId());
        payload.put("botId", identity.getBotId());
        payload.put("origin", identity.getOrigin());
        redisTemplate.opsForValue().set(
                key(ticket), payload.toJSONString(), TTL_SECONDS, java.util.concurrent.TimeUnit.SECONDS);
        return ticket;
    }

    /**
     * 原子消费一张票据。返回 null 表示票不存在、已用过或已过期——
     * **三种情况故意不区分**：区分开来等于告诉调用方"这张票存在过"。
     */
    public TicketIdentity consume(String ticket, String requestOrigin) {
        if (ticket == null || ticket.trim().isEmpty()) {
            return null;
        }
        String stored = redisTemplate.execute(
                CONSUME_SCRIPT, Collections.singletonList(key(ticket.trim())));
        if (stored == null) {
            return null;
        }
        JSONObject payload;
        try {
            payload = JSON.parseObject(stored);
        } catch (RuntimeException ex) {
            log.warn("conversation ws ticket payload is unreadable");
            return null;
        }
        if (payload == null) {
            return null;
        }
        String boundOrigin = payload.getString("origin");
        if (boundOrigin != null && !boundOrigin.isEmpty() && requestOrigin != null
                && !boundOrigin.equals(requestOrigin)) {
            // 票被换了个来源用：拒绝。票据与来源绑定，不做通配。
            log.warn("conversation ws ticket origin mismatch");
            return null;
        }
        return TicketIdentity.builder()
                .tenantId(payload.getLong("tenantId"))
                .sessionId(payload.getLong("sessionId"))
                .userId(payload.getLong("userId"))
                .botId(payload.getLong("botId"))
                .origin(boundOrigin)
                .build();
    }

    static String key(String ticket) {
        return KEY_PREFIX + sha256Hex(ticket);
    }

    static String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(bytes.length * 2);
            for (byte item : bytes) {
                builder.append(Character.forDigit((item >> 4) & 0xF, 16));
                builder.append(Character.forDigit(item & 0xF, 16));
            }
            return builder.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 unavailable", ex);
        }
    }
}
