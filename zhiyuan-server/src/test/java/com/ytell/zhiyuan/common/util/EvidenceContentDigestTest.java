package com.ytell.zhiyuan.common.util;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.mapper.EvidenceLedgerMapper;
import com.ytell.zhiyuan.mapper.EvidenceSourceVersionMapper;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceSignRequest;
import com.ytell.zhiyuan.model.entity.biz.EvidenceLedgerEntity;
import com.ytell.zhiyuan.service.biz.EvidenceLedgerService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 内容摘要函数的确定性与判别性。
 *
 * <p>这四条是摘要能当「数据版本」用的全部前提：同一份内容必须恒定（否则证据无谓失效）、
 * 内容变了必须能分辨（否则失效检测形同虚设）、data 缺失必须不签发。</p>
 */
class EvidenceContentDigestTest {

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

    private Map<String, Object> row(String name, String minScore) {
        Map<String, Object> item = Maps.newLinkedHashMap();
        item.put("name", name);
        item.put("minScore", minScore);
        item.put("year", 2025);
        return item;
    }

    @Test
    void sameDataDigestsIdentically() {
        String first = EvidenceContentDigest.digest(Lists.newArrayList(row("甲大学", "612")));
        String second = EvidenceContentDigest.digest(Lists.newArrayList(row("甲大学", "612")));

        assertEquals(first, second);
        assertEquals(32, first.length());
    }

    @Test
    void keyOrderDoesNotChangeDigest() {
        Map<String, Object> ascending = new LinkedHashMap<String, Object>();
        ascending.put("areaId", "330000");
        ascending.put("schoolId", "school-1");

        Map<String, Object> descending = new LinkedHashMap<String, Object>();
        descending.put("schoolId", "school-1");
        descending.put("areaId", "330000");

        assertEquals(EvidenceContentDigest.digest(ascending), EvidenceContentDigest.digest(descending));
    }

    @Test
    void arrayOrderChangesDigest() {
        List<Map<String, Object>> ascending = Lists.newArrayList(row("甲大学", "612"), row("乙大学", "580"));
        List<Map<String, Object>> descending = Lists.newArrayList(row("乙大学", "580"), row("甲大学", "612"));

        assertNotEquals(EvidenceContentDigest.digest(ascending), EvidenceContentDigest.digest(descending));
    }

    @Test
    void nullDataIsNotSigned() {
        when(evidenceLedgerMapper.insert(any(EvidenceLedgerEntity.class))).thenReturn(1);

        String dataVersion = EvidenceContentDigest.digest(null);
        assertNull(dataVersion);

        EvidenceSignRequest request = EvidenceSignRequest.query(
                SOURCE, dataVersion, Maps.newLinkedHashMap(), EvidenceScope.of(7L, 42L, "thread-1"));
        assertNull(service.sign(request));

        verify(evidenceLedgerMapper, never()).insert(any(EvidenceLedgerEntity.class));
        verify(evidenceSourceVersionMapper, never())
                .upsert(any(), any(), any(), any());
    }

    @Test
    void absentKeyAndNullValuedKeyDigestIdentically() {
        Map<String, Object> withNull = Maps.newLinkedHashMap();
        withNull.put("name", "甲大学");
        withNull.put("minScore", null);

        Map<String, Object> withoutKey = Maps.newLinkedHashMap();
        withoutKey.put("name", "甲大学");

        assertEquals(EvidenceContentDigest.digest(withNull), EvidenceContentDigest.digest(withoutKey));
    }
}
