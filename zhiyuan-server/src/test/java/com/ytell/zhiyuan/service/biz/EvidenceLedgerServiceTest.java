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

import java.util.Collections;

import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
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
        when(evidenceSourceVersionMapper.upsert(anyString(), anyString(), anyString(), any(Date.class))).thenReturn(1);

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
        verify(evidenceSourceVersionMapper).upsert(eq(SOURCE), anyString(), eq("2026-06-v17"), any(Date.class));
    }

    @Test
    void shouldNotSignWhenUpstreamDataVersionMissing() {
        when(evidenceLedgerMapper.insert(any(EvidenceLedgerEntity.class))).thenReturn(1);

        assertNull(service.sign(request(null, EvidenceScope.of(7L, 42L, "thread-1"))));
        assertNull(service.sign(request("  ", EvidenceScope.of(7L, 42L, "thread-1"))));

        verify(evidenceLedgerMapper, never()).insert(any(EvidenceLedgerEntity.class));
        verify(evidenceSourceVersionMapper, never()).upsert(anyString(), anyString(), anyString(), any(Date.class));
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
        when(evidenceSourceVersionMapper.upsert(anyString(), anyString(), anyString(), any(Date.class))).thenReturn(1);

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
        entity.setParamsDigest("0123456789abcdef0123456789abcdef");
        entity.setDataVersion(dataVersion);
        entity.setObservedAt(new Date());
        return entity;
    }

    @Test
    void shouldReturnExpiredWhenExpiresAtMissing() {
        // 2026-09-22 裁决：没有过期时间 = 新鲜度未知 = `expired`（必须重查），
        // 与快照那条路（SQL `expires_at > now`，NULL 进不去）统一到 fail-closed。
        // 在此之前核验这条路把 NULL 当"永不过期"，同一条记录两个口径。
        when(evidenceLedgerMapper.selectById("ev_noexpiry")).thenReturn(stored("ev_noexpiry", "2026-06-v17", null));
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString()))
                .thenReturn(sourceVersion("2026-06-v17"));

        assertEquals("expired", service.verify(verifyRequest("ev_noexpiry")).getResults().get("ev_noexpiry").getStatus());
    }

    @Test
    void shouldDegradeToNoEvidenceWhenTheLedgerQueryFails() {
        // P1b-3 任务书步骤 1：查库异常 → **记 ERROR、返回空列表、snapshot 照常返回**。
        // 与 sign() 同一方向（"不把一次取证失败放大成取数据失败"）：证据缺席可以降级，
        // 整轮对话失败不能——快照失败在链路上就是"当前会话状态暂时不可用"。
        when(evidenceLedgerMapper.selectList(any())).thenThrow(new RuntimeException("db down"));

        assertTrue(service.listSessionEvidence(7L, 42L, new Date()).isEmpty());
    }

    @Test
    void shouldDegradeToNoEvidenceWhenTheVersionLookupFails() {
        // 版本查不到就分不出 valid 与 stale。**整批降级为空**是刻意的：
        // 拿不准的那些宁可不摆到模型面前，而不是赌它们没过期。
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectList(any()))
                .thenReturn(Lists.newArrayList(stored("ev_1", "2026-06-v17", future)));
        when(evidenceSourceVersionMapper.selectBySourceAndParams(anyString(), anyString()))
                .thenThrow(new RuntimeException("db down"));

        assertTrue(service.listSessionEvidence(7L, 42L, new Date()).isEmpty());
    }

    @Test
    void shouldListOnlyValidEvidenceAndDropStaleOnes() {
        // P1b-3 的核心验收：快照**只放 valid**。对照是硬要求——
        // 只断言"stale 不在"的话，"整个列表被清空"也能让它通过。
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectList(any()))
                .thenReturn(Lists.newArrayList(
                        stored("ev_valid", "2026-06-v17", future),
                        stored("ev_stale", "2026-06-v16", future)));
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString()))
                .thenReturn(sourceVersion("2026-06-v17"));

        List<ConversationEvidenceDTO> listed = service.listSessionEvidence(7L, 42L, new Date());

        assertEquals(1, listed.size(), listed.toString());
        assertEquals("ev_valid", listed.get(0).getEvidenceId());
    }

    @Test
    void shouldDropEvidenceWhoseSourceVersionRowIsGone() {
        // 版本行没了 ⇒ currentDataVersion 回 ""（`verifyOne` 的同一条语义），
        // 与记录里的摘要必然不等 ⇒ 判 stale、不进快照。
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectList(any()))
                .thenReturn(Lists.newArrayList(stored("ev_orphan", "2026-06-v17", future)));
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString()))
                .thenReturn(null);

        assertTrue(service.listSessionEvidence(7L, 42L, new Date()).isEmpty());
    }

    @Test
    void shouldReturnValidWhenVersionMatchesUpstream() {
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_ok")).thenReturn(stored("ev_ok", "2026-06-v17", future));
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString()))
                .thenReturn(sourceVersion("2026-06-v17"));

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
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString()))
                .thenReturn(sourceVersion("2026-06-v17"));

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
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString()))
                .thenReturn(sourceVersion("2026-06-v17"));

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

        EvidenceVerifyReq otherTenant = verifyRequest("ev_other");
        otherTenant.setTenantId(8L);
        assertEquals("unknown", service.verify(otherTenant).getResults().get("ev_other").getStatus());
    }

    @Test
    void shouldVerifyEvidenceSignedInAnotherThreadOfTheSameSession() {
        // 2026-10-08 实机事故：Gateway 重启后同一会话换新 thread，模型引用了重启前签发的
        // 证据（快照还把它摆在模型面前请它引用），却被线程等值检查判成 unknown，而
        // P1c-2 分流表对 unknown 是硬失败——整轮作废（会话 10041979）。
        // 2026-09-13 裁决：thread 不是证据的隔离边界（thread_id 进程易失），
        // 不参与准入判定；这里把裁决钉住。
        // 对照：换会话/换租户仍 unknown（上一条用例），台账无记录仍 unknown
        // （shouldReturnUnknownWhenRecordDeleted）。
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_prev_thread"))
                .thenReturn(stored("ev_prev_thread", "2026-06-v17", future));
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString()))
                .thenReturn(sourceVersion("2026-06-v17"));

        EvidenceVerifyReq otherThread = verifyRequest("ev_prev_thread");
        otherThread.setThreadId("thread-2");

        assertEquals("valid", service.verify(otherThread).getResults().get("ev_prev_thread").getStatus());
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
    void shouldReturnUnknownWhenNoSourceVersionObserved() {
        // P1c-2：版本记录缺失 = **"我没有当前版本的记录"** = `unknown`，
        // 不是 `stale`（"当前版本跟你签的不一样"）。这条用例原来断言的是 `stale`，
        // 它编码的正是那处混用——P1b-1 复核第六节把它记成了隐患。
        // 对照在下一条：版本行在、摘要不同 → 仍是 `stale`。
        Date future = new Date(System.currentTimeMillis() + TimeUnit.DAYS.toMillis(30));
        when(evidenceLedgerMapper.selectById("ev_nover")).thenReturn(stored("ev_nover", "2026-06-v17", future));
        when(evidenceSourceVersionMapper.selectBySourceAndParams(eq(SOURCE), anyString())).thenReturn(null);

        assertEquals("unknown", service.verify(verifyRequest("ev_nover")).getResults().get("ev_nover").getStatus());
    }

    @Test
    void listSessionEvidenceOnlyReturnsUnexpiredAndCurrentRowsForTheSameSession() {
        // 语义自 2026-09-22 起是"未过期**且**版本仍是最新的"：这条用例原来只铺了
        // "未过期"，于是按新语义它会被判 stale 而滤掉——补上版本行，让它继续验
        // 它本来要验的那件事（同会话、未过期的行会被返回）。
        EvidenceLedgerEntity valid = new EvidenceLedgerEntity();
        valid.setEvidenceId("ev_valid");
        valid.setTenantId(1L);
        valid.setChatSessionId(2L);
        valid.setSourceSystem(EvidenceLedgerService.SOURCE_GAOTU_SCHOOL_MAJOR_SCORE_LINE);
        valid.setParamsDigest("d1");
        valid.setDataVersion("sha256:abc");
        valid.setObservedAt(new Date());
        valid.setExpiresAt(new Date(System.currentTimeMillis() + 3_600_000L));
        valid.setScopeJson("{}");
        valid.setLimitationsJson("[]");

        EvidenceSourceVersionEntity current = new EvidenceSourceVersionEntity();
        current.setSourceSystem(EvidenceLedgerService.SOURCE_GAOTU_SCHOOL_MAJOR_SCORE_LINE);
        current.setParamsDigest("d1");
        current.setDataVersion("sha256:abc");
        when(evidenceSourceVersionMapper.selectBySourceAndParams(
                eq(EvidenceLedgerService.SOURCE_GAOTU_SCHOOL_MAJOR_SCORE_LINE), eq("d1")))
                .thenReturn(current);

        when(evidenceLedgerMapper.selectList(any())).thenReturn(Collections.singletonList(valid));

        List<ConversationEvidenceDTO> evidence = service.listSessionEvidence(1L, 2L, new Date());

        assertEquals(1, evidence.size());
        assertEquals("ev_valid", evidence.get(0).getEvidenceId());
    }

    @Test
    void listSessionEvidenceReturnsEmptyWithoutScope() {
        // 少了租户或会话就没有隔离边界可言：宁可回空，也不能回"全部"。
        assertTrue(service.listSessionEvidence(null, 2L, new Date()).isEmpty());
        assertTrue(service.listSessionEvidence(1L, null, new Date()).isEmpty());
        verify(evidenceLedgerMapper, never()).selectList(any());
    }
}
