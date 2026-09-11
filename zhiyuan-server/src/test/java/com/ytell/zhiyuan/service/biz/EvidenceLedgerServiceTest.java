package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.mapper.EvidenceLedgerMapper;
import com.ytell.zhiyuan.mapper.EvidenceSourceVersionMapper;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceSignRequest;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyItemDTO;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyReq;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyRes;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.entity.biz.EvidenceLedgerEntity;
import com.ytell.zhiyuan.model.entity.biz.EvidenceSourceVersionEntity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class EvidenceLedgerServiceTest {

    private static final String SOURCE = "gaotu.schoolMajorScoreLine";

    private EvidenceLedgerMapper evidenceLedgerMapper;
    private EvidenceSourceVersionMapper evidenceSourceVersionMapper;
    private EvidenceLedgerService service;

    @BeforeEach
    void setUp() {
        evidenceLedgerMapper = Mockito.mock(EvidenceLedgerMapper.class);
        evidenceSourceVersionMapper = Mockito.mock(EvidenceSourceVersionMapper.class);
        service = new EvidenceLedgerService();
        ReflectionTestUtils.setField(service, "evidenceLedgerMapper", evidenceLedgerMapper);
        ReflectionTestUtils.setField(service, "evidenceSourceVersionMapper", evidenceSourceVersionMapper);
        ReflectionTestUtils.setField(service, "ttlDays", 30);
    }

    private Map<String, Object> params() {
        Map<String, Object> params = Maps.newLinkedHashMap();
        params.put("areaId", "330000");
        params.put("schoolId", "school-1");
        return params;
    }

    private EvidenceSignRequest request(String dataVersion, EvidenceScope scope) {
        return EvidenceSignRequest.query(SOURCE, dataVersion, params(), scope);
    }

    @Test
    void shouldSignAndRecordWhenVersionAndScopePresent() {
        EvidenceScope scope = EvidenceScope.of(7L, 42L, "thread-1");
        when(evidenceLedgerMapper.insert(any(EvidenceLedgerEntity.class))).thenReturn(1);
        when(evidenceSourceVersionMapper.upsert(anyString(), anyString(), any(Date.class))).thenReturn(1);

        ConversationEvidenceDTO evidence = service.sign(request("2026-06-v17", scope));

        assertNotNull(evidence);
        assertTrue(evidence.getEvidenceId().startsWith("ev_"), evidence.getEvidenceId());
        assertEquals(29, evidence.getEvidenceId().length());
        assertEquals("authoritative", evidence.getSourceLevel());
        assertEquals(SOURCE, evidence.getSourceSystem());
        assertEquals("2026-06-v17", evidence.getDataVersion());
        assertEquals(32, evidence.getParamsDigest().length());
        assertNotNull(evidence.getObservedAt());
        assertNotNull(evidence.getExpiresAt());
        assertEquals(7L, evidence.getScope().get("tenantId"));
        assertEquals(42L, evidence.getScope().get("chatSessionId"));

        ArgumentCaptor<EvidenceLedgerEntity> captor = ArgumentCaptor.forClass(EvidenceLedgerEntity.class);
        verify(evidenceLedgerMapper).insert(captor.capture());
        EvidenceLedgerEntity stored = captor.getValue();
        assertEquals("2026-06-v17", stored.getDataVersion());
        assertEquals(7L, stored.getTenantId());
        assertEquals(42L, stored.getChatSessionId());
        assertEquals("thread-1", stored.getThreadId());
        assertEquals(evidence.getEvidenceId(), stored.getEvidenceId());
        assertEquals(evidence.getParamsDigest(), stored.getParamsDigest());
        assertTrue(stored.getExpiresAt().after(stored.getObservedAt()));
        verify(evidenceSourceVersionMapper).upsert(eq(SOURCE), eq("2026-06-v17"), any(Date.class));
    }

    @Test
    void shouldNotSignWhenUpstreamDataVersionMissing() {
        when(evidenceLedgerMapper.insert(any(EvidenceLedgerEntity.class))).thenReturn(1);

        assertNull(service.sign(request(null, EvidenceScope.of(7L, 42L, "thread-1"))));
        assertNull(service.sign(request("  ", EvidenceScope.of(7L, 42L, "thread-1"))));

        verify(evidenceLedgerMapper, never()).insert(any(EvidenceLedgerEntity.class));
        verify(evidenceSourceVersionMapper, never()).upsert(anyString(), anyString(), any(Date.class));
    }

    @Test
    void shouldNotSignWhenScopeIncomplete() {
        when(evidenceLedgerMapper.insert(any(EvidenceLedgerEntity.class))).thenReturn(1);

        assertNull(service.sign(request("2026-06-v17", EvidenceScope.none())));
        assertNull(service.sign(request("2026-06-v17", EvidenceScope.of(7L, null, "thread-1"))));
        assertNull(service.sign(request("2026-06-v17", null)));

        verify(evidenceLedgerMapper, never()).insert(any(EvidenceLedgerEntity.class));
    }

    @Test
    void shouldGenerateDifferentEvidenceIdsForRepeatedIdenticalQuery() {
        when(evidenceLedgerMapper.insert(any(EvidenceLedgerEntity.class))).thenReturn(1);
        when(evidenceSourceVersionMapper.upsert(anyString(), anyString(), any(Date.class))).thenReturn(1);

        ConversationEvidenceDTO first = service.sign(request("2026-06-v17", EvidenceScope.of(7L, 42L, "thread-1")));
        ConversationEvidenceDTO second = service.sign(request("2026-06-v17", EvidenceScope.of(7L, 42L, "thread-1")));

        assertNotNull(first);
        assertNotNull(second);
        assertTrue(!first.getEvidenceId().equals(second.getEvidenceId()));
        assertEquals(first.getParamsDigest(), second.getParamsDigest());
    }

    private EvidenceVerifyReq verifyRequest(String evidenceId) {
        EvidenceVerifyReq req = new EvidenceVerifyReq();
        req.setTenantId(7L);
        req.setChatSessionId(42L);
        req.setThreadId("thread-1");
        req.setEvidenceIds(Lists.newArrayList(evidenceId));
        return req;
    }

    private EvidenceLedgerEntity stored(String evidenceId, String dataVersion, Date expiresAt) {
        EvidenceLedgerEntity entity = new EvidenceLedgerEntity();
        entity.setEvidenceId(evidenceId);
        entity.setTenantId(7L);
        entity.setChatSessionId(42L);
        entity.setThreadId("thread-1");
        entity.setSourceSystem(SOURCE);
        entity.setParamsDigest("0123456789abcdef0123456789abcdef");
        entity.setDataVersion(dataVersion);
        entity.setObservedAt(new Date(System.currentTimeMillis() - TimeUnit.DAYS.toMillis(1)));
        entity.setExpiresAt(expiresAt);
        return entity;
    }

    private EvidenceSourceVersionEntity sourceVersion(String dataVersion) {
        EvidenceSourceVersionEntity entity = new EvidenceSourceVersionEntity();
        entity.setSourceSystem(SOURCE);
        entity.setDataVersion(dataVersion);
        entity.setObservedAt(new Date());
        return entity;
    }

    @Test
    void shouldReturnValidWhenVersionMatchesUpstream() {
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_ok")).thenReturn(stored("ev_ok", "2026-06-v17", future));
        when(evidenceSourceVersionMapper.selectById(SOURCE)).thenReturn(sourceVersion("2026-06-v17"));

        EvidenceVerifyRes response = service.verify(verifyRequest("ev_ok"));

        EvidenceVerifyItemDTO item = response.getResults().get("ev_ok");
        assertEquals("valid", item.getStatus());
        assertEquals(SOURCE, item.getSourceSystem());
        assertEquals("0123456789abcdef0123456789abcdef", item.getParamsDigest());
        assertEquals("2026-06-v17", item.getDataVersion());
        assertNotNull(item.getObservedAt());
        assertNotNull(item.getExpiresAt());
    }

    @Test
    void shouldReturnStaleWhenVersionDiffersFromUpstream() {
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_stale")).thenReturn(stored("ev_stale", "2026-06-v16", future));
        when(evidenceSourceVersionMapper.selectById(SOURCE)).thenReturn(sourceVersion("2026-06-v17"));

        EvidenceVerifyRes response = service.verify(verifyRequest("ev_stale"));

        assertEquals("stale", response.getResults().get("ev_stale").getStatus());
    }

    @Test
    void shouldReturnUnknownWhenRecordDeleted() {
        when(evidenceLedgerMapper.selectById("ev_gone")).thenReturn(null);

        EvidenceVerifyRes response = service.verify(verifyRequest("ev_gone"));

        assertEquals("unknown", response.getResults().get("ev_gone").getStatus());
    }

    @Test
    void shouldReturnExpiredWhenPastExpiresAt() {
        Date past = new Date(System.currentTimeMillis() - TimeUnit.DAYS.toMillis(1));
        when(evidenceLedgerMapper.selectById("ev_old")).thenReturn(stored("ev_old", "2026-06-v17", past));
        when(evidenceSourceVersionMapper.selectById(SOURCE)).thenReturn(sourceVersion("2026-06-v17"));

        EvidenceVerifyRes response = service.verify(verifyRequest("ev_old"));

        assertEquals("expired", response.getResults().get("ev_old").getStatus());
    }

    @Test
    void shouldReturnUnknownWhenScopeDoesNotMatch() {
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_other")).thenReturn(stored("ev_other", "2026-06-v17", future));

        EvidenceVerifyReq req = verifyRequest("ev_other");
        req.setChatSessionId(43L);
        assertEquals("unknown", service.verify(req).getResults().get("ev_other").getStatus());

        EvidenceVerifyReq otherThread = verifyRequest("ev_other");
        otherThread.setThreadId("thread-2");
        assertEquals("unknown", service.verify(otherThread).getResults().get("ev_other").getStatus());
    }

    @Test
    void shouldReturnEmptyResultForNullRequest() {
        assertTrue(service.verify(null).getResults().isEmpty());
    }

    @Test
    void shouldReturnUnknownWhenVerifyRequestHasNoScope() {
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_scoped")).thenReturn(stored("ev_scoped", "2026-06-v17", future));

        EvidenceVerifyReq req = new EvidenceVerifyReq();
        req.setEvidenceIds(Lists.newArrayList("ev_scoped"));

        assertEquals("unknown", service.verify(req).getResults().get("ev_scoped").getStatus());
    }

    @Test
    void shouldReturnStaleWhenNoSourceVersionObserved() {
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_nover")).thenReturn(stored("ev_nover", "2026-06-v17", future));
        when(evidenceSourceVersionMapper.selectById(SOURCE)).thenReturn(null);

        assertEquals("stale", service.verify(verifyRequest("ev_nover")).getResults().get("ev_nover").getStatus());
    }
}
