package com.ytell.zhiyuan.manager.cache;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.model.dto.conversation.TicketIdentity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

public class ConversationWsTicketStoreTest {

    private ConversationWsTicketStore store;
    private StringRedisTemplate redisTemplate;
    private ValueOperations<String, String> valueOperations;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        store = new ConversationWsTicketStore();
        redisTemplate = Mockito.mock(StringRedisTemplate.class);
        valueOperations = Mockito.mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        ReflectionTestUtils.setField(store, "redisTemplate", redisTemplate);
    }

    @Test
    void theTicketItselfIsNeverUsedAsTheRedisKey() {
        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);

        String ticket = store.issue(TicketIdentity.builder().tenantId(1L).sessionId(2L).userId(3L).build());

        Mockito.verify(valueOperations).set(keyCaptor.capture(), anyString(), any(Long.class), any());
        String key = keyCaptor.getValue();

        // 票被读到也不能拿去连：库里存的是哈希。
        assertTrue(key.startsWith("conv:ws-ticket:"));
        assertNotEquals("conv:ws-ticket:" + ticket, key);
        assertEquals("conv:ws-ticket:" + ConversationWsTicketStore.sha256Hex(ticket), key);
    }

    @Test
    @SuppressWarnings("unchecked")
    void theIssuedTicketIsUnpredictableAndUrlSafe() {
        String first = store.issue(TicketIdentity.builder().tenantId(1L).sessionId(2L).userId(3L).build());
        String second = store.issue(TicketIdentity.builder().tenantId(1L).sessionId(2L).userId(3L).build());

        assertNotEquals(first, second);
        // 32 字节 base64url 无填充 = 43 字符：够长，且不会在 URL 里被转义。
        assertEquals(43, first.length());
        assertTrue(first.matches("[A-Za-z0-9_-]+"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void consumeReturnsNullOnAnAlreadyUsedTicket() {
        // 脚本已经 DEL 掉了：再消费拿到 null——不存在与已用过刻意不区分。
        when(redisTemplate.execute(any(RedisScript.class), anyList())).thenReturn(null);

        assertNull(store.consume("used-ticket", "http://127.0.0.1:3201"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void consumeUsesASingleScriptCallSoReadAndDeleteCannotBeSplit() {
        JSONObject payload = new JSONObject();
        payload.put("tenantId", 1L);
        payload.put("sessionId", 2L);
        payload.put("userId", 3L);
        payload.put("origin", "http://127.0.0.1:3201");
        when(redisTemplate.execute(any(RedisScript.class), anyList())).thenReturn(payload.toJSONString());

        store.consume("fresh", "http://127.0.0.1:3201");

        // 一次 execute = 一段 Lua 里完成 GET+DEL。拆成两次会出现
        // "两个连接同时读到同一张票"的窗口。
        Mockito.verify(redisTemplate, Mockito.times(1)).execute(any(RedisScript.class), anyList());
    }

    @Test
    @SuppressWarnings("unchecked")
    void aTicketIsRefusedFromAnotherOrigin() {
        JSONObject payload = new JSONObject();
        payload.put("tenantId", 1L);
        payload.put("origin", "http://127.0.0.1:3201");
        when(redisTemplate.execute(any(RedisScript.class), anyList())).thenReturn(payload.toJSONString());

        assertNull(store.consume("fresh", "https://evil.example.com"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void consumeReturnsTheIdentityWhenEverythingMatches() {
        JSONObject payload = new JSONObject();
        payload.put("tenantId", 1L);
        payload.put("sessionId", 2L);
        payload.put("userId", 3L);
        payload.put("botId", 4L);
        payload.put("origin", "http://127.0.0.1:3201");
        when(redisTemplate.execute(any(RedisScript.class), anyList())).thenReturn(payload.toJSONString());

        TicketIdentity identity = store.consume("fresh", "http://127.0.0.1:3201");

        assertEquals(1L, identity.getTenantId());
        assertEquals(2L, identity.getSessionId());
        assertEquals(3L, identity.getUserId());
        assertEquals(4L, identity.getBotId());
    }

    @Test
    @SuppressWarnings("unchecked")
    void anEmptyOrBlankTicketNeverTouchesRedis() {
        assertNull(store.consume(null, "http://127.0.0.1:3201"));
        assertNull(store.consume("   ", "http://127.0.0.1:3201"));

        Mockito.verify(redisTemplate, Mockito.never()).execute(any(RedisScript.class), anyList());
    }

    @Test
    @SuppressWarnings("unchecked")
    void anUnreadablePayloadIsRefusedRatherThanTrusted() {
        when(redisTemplate.execute(any(RedisScript.class), anyList())).thenReturn("{not json");

        assertNull(store.consume("fresh", "http://127.0.0.1:3201"));
    }
}
