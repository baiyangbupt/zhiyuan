package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.ConversationArtifactMapper;
import com.ytell.zhiyuan.model.dto.planning.ArtifactDTO;
import com.ytell.zhiyuan.model.dto.planning.ArtifactPageDTO;
import com.ytell.zhiyuan.model.entity.biz.ConversationArtifactEntity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Calendar;
import java.util.Date;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doReturn;

/**
 * 产物存储的**逻辑**层证据。
 *
 * <p>这里证明不了的（跨用户不可读要真 SQL 的 where 生效、重启后可读要真落库）
 * 放在 {@code ConversationArtifactPersistenceIntegrationTest} 里，由环境变量门控，
 * 缺配置时 skip 而**不记为通过**。
 */
public class ConversationArtifactServiceTest {

    private ConversationArtifactService service;
    private ConversationArtifactMapper mapper;

    @BeforeEach
    void setUp() {
        service = new ConversationArtifactService();
        mapper = Mockito.mock(ConversationArtifactMapper.class);
        ReflectionTestUtils.setField(service, "artifactMapper", mapper);
    }

    @Test
    void putComputesDigestOverCanonicalContentNotInsertionOrder() {
        Map<String, Object> first = new HashMap<>();
        first.put("alpha", 1);
        first.put("beta", 2);
        Map<String, Object> second = new HashMap<>();
        second.put("beta", 2);
        second.put("alpha", 1);

        String left = ConversationArtifactService.canonicalJson(first);
        String right = ConversationArtifactService.canonicalJson(second);

        // 同一份数据的两种构造顺序必须得到同一个摘要：否则下游会把"没变"当成"变了"。
        assertEquals(left, right);
        assertEquals(ConversationArtifactService.digest(left), ConversationArtifactService.digest(right));
    }

    @Test
    void putRefusesOversizedPayloadInsteadOfTruncating() {
        JSONObject big = new JSONObject();
        big.put("blob", repeat('x', ConversationArtifactService.MAX_PAYLOAD_BYTES + 16));

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.put(1L, 2L, "candidate", big, null, tomorrow()));

        assertEquals(413, ex.getStatus());
    }

    @Test
    void putRequiresAnExpiry() {
        // 没有有效期的产物会在库里永久存活，而它引用的画像/工作区版本早就变了。
        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.put(1L, 2L, "candidate", new JSONObject(), null, null));

        assertEquals(400, ex.getStatus());
    }

    @Test
    void putStoresDigestOfWhatWasActuallyWritten() {
        doReturn(1).when(mapper).insert(any(ConversationArtifactEntity.class));
        ArgumentCaptor<ConversationArtifactEntity> captor =
                ArgumentCaptor.forClass(ConversationArtifactEntity.class);

        String artifactId = service.put(1L, 2L, "candidate", payload(3), null, tomorrow());

        Mockito.verify(mapper).insert(captor.capture());
        ConversationArtifactEntity saved = captor.getValue();
        assertNotNull(artifactId);
        assertTrue(artifactId.startsWith("art_"));
        assertEquals(ConversationArtifactService.digest(saved.getPayloadJson()), saved.getPayloadDigest());
    }

    @Test
    void getOwnedRejectsAnExpiredArtifact() {
        doReturn(entity("art_1", 1L, 2L, expired())).when(mapper).selectOne(any(QueryWrapper.class));

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.getOwned(1L, 2L, "art_1"));

        assertEquals(410, ex.getStatus());
    }

    @Test
    void getOwnedRejectsContentThatNoLongerMatchesItsDigest() {
        ConversationArtifactEntity tampered = entity("art_2", 1L, 2L, tomorrow());
        tampered.setPayloadJson("{\"items\":[],\"extra\":\"injected\"}");
        doReturn(tampered).when(mapper).selectOne(any(QueryWrapper.class));

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.getOwned(1L, 2L, "art_2"));

        // 内容与签名对不上：可能是被改过，也可能是写入时就算错了。两种都不能交出去。
        assertEquals(500, ex.getStatus());
        assertEquals("artifact_digest_mismatch", ex.getMessage());
    }

    @Test
    void pageOwnedCapsThePageSizeAndReturnsACursor() {
        // 60 条才能**观察到** 50 的上限：给 25 条数据的话，即使上限没生效
        // 结果也一样，这条测试就变成了空的。
        doReturn(entity("art_3", 1L, 2L, tomorrow(), 60)).when(mapper).selectOne(any(QueryWrapper.class));

        ArtifactPageDTO first = service.pageOwned(1L, 2L, "art_3", null, 100);

        assertEquals(ConversationArtifactService.MAX_PAGE_SIZE, first.getItems().size());
        assertNotNull(first.getNextCursor());
        assertEquals(60, first.getTotal());

        ArtifactPageDTO rest = service.pageOwned(1L, 2L, "art_3", first.getNextCursor(), 50);
        assertEquals(10, rest.getItems().size());
        assertNull(rest.getNextCursor(), "最后一页没有下一页游标");
    }

    @Test
    void pageOwnedRejectsAnInvalidCursorInsteadOfSilentlyStartingOver() {
        doReturn(entity("art_4", 1L, 2L, tomorrow())).when(mapper).selectOne(any(QueryWrapper.class));

        // 静默从头开始会让用户以为自己在看第二页，其实是第一页。
        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.pageOwned(1L, 2L, "art_4", "not-a-cursor", 10));

        assertEquals(400, ex.getStatus());
    }

    @Test
    void missingArtifactAndForeignArtifactLookTheSame() {
        doReturn(null).when(mapper).selectOne(any(QueryWrapper.class));

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.getOwned(1L, 2L, "art_missing"));

        // 区分"不存在"和"不属于你"等于确认了一次越权探测：对方能据此判断 id 存在与否。
        assertEquals(404, ex.getStatus());
        assertEquals("artifact_not_found", ex.getMessage());
    }

    private static String repeat(char value, int times) {
        StringBuilder builder = new StringBuilder(times);
        for (int index = 0; index < times; index++) {
            builder.append(value);
        }
        return builder.toString();
    }

    private static JSONObject payload(int itemCount) {
        JSONArray items = new JSONArray();
        for (int index = 0; index < itemCount; index++) {
            JSONObject item = new JSONObject();
            item.put("schoolId", "school-" + index);
            items.add(item);
        }
        JSONObject payload = new JSONObject();
        payload.put("items", items);
        return payload;
    }

    private static ConversationArtifactEntity entity(String artifactId, Long tenantId, Long sessionId, Date expiresAt) {
        return entity(artifactId, tenantId, sessionId, expiresAt, 25);
    }

    private static ConversationArtifactEntity entity(String artifactId, Long tenantId, Long sessionId,
                                                     Date expiresAt, int itemCount) {
        JSONObject payload = payload(itemCount);
        String json = ConversationArtifactService.canonicalJson(payload);
        ConversationArtifactEntity entity = new ConversationArtifactEntity();
        entity.setArtifactId(artifactId);
        entity.setTenantId(tenantId);
        entity.setChatSessionId(sessionId);
        entity.setKind("candidate");
        entity.setPayloadJson(json);
        entity.setPayloadDigest(ConversationArtifactService.digest(json));
        entity.setDependenciesJson("{}");
        entity.setExpiresAt(expiresAt);
        entity.setCreateTime(new Date());
        return entity;
    }

    private static Date tomorrow() {
        Calendar calendar = Calendar.getInstance();
        calendar.add(Calendar.DAY_OF_MONTH, 1);
        return calendar.getTime();
    }

    private static Date expired() {
        Calendar calendar = Calendar.getInstance();
        calendar.add(Calendar.MINUTE, -1);
        return calendar.getTime();
    }

    @Test
    void returnedPayloadIsTheStoredOne() {
        doReturn(entity("art_5", 1L, 2L, tomorrow())).when(mapper).selectOne(any(QueryWrapper.class));

        ArtifactDTO dto = service.getOwned(1L, 2L, "art_5");

        assertEquals("art_5", dto.getArtifactId());
        assertEquals("candidate", dto.getKind());
        assertEquals(25, ((JSONArray) dto.getPayload().get("items")).size());
    }
}
