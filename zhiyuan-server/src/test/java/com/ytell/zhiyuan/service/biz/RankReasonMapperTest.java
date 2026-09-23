package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.volunteer.RankReasonDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * P1d 步骤 2：rank 内部标签 → 稳定结构化理由。
 *
 * 本文件的重点是**两条"不装懂"**：认不出的标签不许丢、没有权重的不许补 0。
 * 它们是这一层最容易在"让它先跑起来"的名义下被放宽的地方。
 */
class RankReasonMapperTest {

    private final RankReasonMapper mapper = new RankReasonMapper();

    private static Map<String, Object> factor(String tag, double delta) {
        Map<String, Object> item = new LinkedHashMap<String, Object>();
        item.put("tag", tag);
        item.put("delta", delta);
        return item;
    }

    @Test
    void shouldMapAKnownTagToAStableCodeAndKeepTheObservedDelta() {
        List<RankReasonDTO> reasons = mapper.mapCollege(
                Arrays.asList(factor("院校正向加分", 24.0)), Collections.singletonMap("level_score", 0.42));

        assertEquals(1, reasons.size());
        assertEquals("school.positive", reasons.get(0).getCode());
        assertEquals(24.0, reasons.get(0).getDelta());
        assertEquals("意向院校", reasons.get(0).getName());
    }

    @Test
    void shouldOmitTheWeightInsteadOfDefaultingToZero() {
        // `院校正向加分` 这类"意向调整"没有对应权重——**不设**，而不是补 0。
        // 补 0 会让"没有这个权重"与"权重是零"长得一模一样。
        List<RankReasonDTO> reasons = mapper.mapCollege(
                Arrays.asList(factor("院校正向加分", 24.0)), Collections.singletonMap("level_score", 0.42));

        assertNull(reasons.get(0).getWeight());
    }

    @Test
    void shouldCarryTheWeightWhenTheFactorHasOne() {
        List<RankReasonDTO> reasons = mapper.mapCollege(
                Arrays.asList(factor("院校层次正向加分", 8.0)), Collections.singletonMap("level_score", 0.42));

        assertEquals(0.42, reasons.get(0).getWeight());
        assertEquals("school.level.positive", reasons.get(0).getCode());
        assertTrue(reasons.get(0).getReason().contains("0.4200"), reasons.get(0).getReason());
        assertTrue(reasons.get(0).getReason().contains("8.00"), reasons.get(0).getReason());
    }

    @Test
    void shouldKeepAnUnknownTagWithAPrefixInsteadOfDroppingIt() {
        // 认不出**不装懂、也不丢**：静默丢弃会让"为什么加分"少一条，
        // 而少的那条恰恰是 rank 新加的规则。
        List<RankReasonDTO> reasons = mapper.mapCollege(
                Arrays.asList(factor("某个以后新加的规则加分", 3.0)), null);

        assertEquals(1, reasons.size());
        assertEquals("unknown:某个以后新加的规则加分", reasons.get(0).getCode());
        assertEquals(3.0, reasons.get(0).getDelta());
        assertTrue(reasons.get(0).getReason().contains("未纳入统一标签体系"));
    }

    @Test
    void shouldMapDynamicIntentTagsByPattern() {
        // rank 会把用户意向标签拼进段名（`计算机类（类）标签正向加分`），没有固定表可查。
        List<RankReasonDTO> reasons = mapper.mapMajor(
                Arrays.asList(factor("计算机类（类）标签正向加分", 4.0)), null);

        assertEquals(1, reasons.size());
        assertEquals("major.group.tag.positive", reasons.get(0).getCode());
        assertEquals("计算机类", reasons.get(0).getName());
        assertEquals(4.0, reasons.get(0).getDelta());
    }

    @Test
    void shouldSkipAFeaturelessFactorButKeepTheRest() {
        List<Map<String, Object>> factors = new ArrayList<Map<String, Object>>();
        Map<String, Object> broken = new LinkedHashMap<String, Object>();
        broken.put("delta", 1.0);
        factors.add(broken);
        factors.add(factor("城市正向加分", 2.0));

        List<RankReasonDTO> reasons = mapper.mapCollege(factors, null);

        assertEquals(1, reasons.size());
        assertEquals("city.positive", reasons.get(0).getCode());
    }

    @Test
    void shouldReturnEmptyForNoFactors() {
        assertTrue(mapper.mapCollege(null, null).isEmpty());
        assertTrue(mapper.mapMajor(Collections.<Map<String, Object>>emptyList(), null).isEmpty());
    }
}
