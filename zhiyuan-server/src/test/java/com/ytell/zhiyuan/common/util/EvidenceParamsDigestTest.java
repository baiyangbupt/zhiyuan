package com.ytell.zhiyuan.common.util;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class EvidenceParamsDigestTest {

    @Test
    void shouldIgnoreKeyOrder() {
        Map<String, Object> first = new LinkedHashMap<String, Object>();
        first.put("batch", "本科批");
        first.put("areaId", "330000");
        Map<String, Object> second = new LinkedHashMap<String, Object>();
        second.put("areaId", "330000");
        second.put("batch", "本科批");

        assertEquals(EvidenceParamsDigest.digest(first), EvidenceParamsDigest.digest(second));
        assertEquals("{\"areaId\":\"330000\",\"batch\":\"本科批\"}", EvidenceParamsDigest.canonical(first));
    }

    @Test
    void shouldDropEmptyValuesAndMissingKeys() {
        Map<String, Object> withEmpty = new LinkedHashMap<String, Object>();
        withEmpty.put("areaId", "330000");
        withEmpty.put("majorId", "");
        withEmpty.put("schoolId", null);
        withEmpty.put("subjectType", "   ");
        withEmpty.put("years", Lists.newArrayList());

        Map<String, Object> onlyPresent = new LinkedHashMap<String, Object>();
        onlyPresent.put("areaId", "330000");

        assertEquals(EvidenceParamsDigest.digest(onlyPresent), EvidenceParamsDigest.digest(withEmpty));
    }

    @Test
    void shouldChangeDigestWhenAnyParamValueChanges() {
        Map<String, Object> original = Maps.newLinkedHashMap();
        original.put("areaId", "330000");
        original.put("year", 2025);

        Map<String, Object> changed = Maps.newLinkedHashMap();
        changed.put("areaId", "330000");
        changed.put("year", 2024);

        assertNotEquals(EvidenceParamsDigest.digest(original), EvidenceParamsDigest.digest(changed));
    }

    @Test
    void shouldTreatNumberAndItsStringFormAsSameValue() {
        Map<String, Object> numeric = Maps.newLinkedHashMap();
        numeric.put("year", 2025);
        Map<String, Object> textual = Maps.newLinkedHashMap();
        textual.put("year", "2025");

        assertEquals(EvidenceParamsDigest.digest(numeric), EvidenceParamsDigest.digest(textual));
    }

    @Test
    void shouldProduceThirtyTwoLowercaseHexChars() {
        Map<String, Object> params = Maps.newLinkedHashMap();
        params.put("schoolId", "school-1");
        String digest = EvidenceParamsDigest.digest(params);

        assertEquals(32, digest.length());
        assertTrue(digest.matches("[0-9a-f]{32}"), digest);
    }

    @Test
    void shouldCanonicalizeNestedMapsBySortedKey() {
        Map<String, Object> scope = new LinkedHashMap<String, Object>();
        scope.put("threadId", "t-1");
        scope.put("tenantId", 7L);
        Map<String, Object> params = Maps.newLinkedHashMap();
        params.put("scope", scope);

        assertEquals("{\"scope\":{\"tenantId\":\"7\",\"threadId\":\"t-1\"}}", EvidenceParamsDigest.canonical(params));
    }
}
