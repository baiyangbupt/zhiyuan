package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class GroupInnerMajorOptimizationFlagsTest {

    @AfterEach
    void clearFlags() {
        System.clearProperty(GroupInnerMajorOptimizationFlags.PROPERTY);
        System.clearProperty(GroupInnerMajorCapFlags.PROPERTY);
    }

    @Test
    void defaultsToOn() {
        assertEquals("on", GroupInnerMajorOptimizationFlags.mode());
        assertTrue(GroupInnerMajorOptimizationFlags.enabled());
        assertFalse(GroupInnerMajorOptimizationFlags.shadow());
    }

    @Test
    void explicitOffRollsBack() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "off");
        assertEquals("off", GroupInnerMajorOptimizationFlags.mode());
        assertFalse(GroupInnerMajorOptimizationFlags.enabled());
    }

    @Test
    void shadowOnlyLogs() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "shadow");
        assertEquals("shadow", GroupInnerMajorOptimizationFlags.mode());
        assertFalse(GroupInnerMajorOptimizationFlags.enabled());
        assertTrue(GroupInnerMajorOptimizationFlags.shadow());
    }
}
