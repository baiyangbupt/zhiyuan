package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class InitialPlanSolverFlagsTest {

    @AfterEach
    void tearDown() {
        System.clearProperty(InitialPlanSolverFlags.PROPERTY);
        System.clearProperty(InitialPlanSolverFlags.SESSIONS_PROPERTY);
    }

    @Test
    void defaultsToOn() {
        assertTrue(InitialPlanSolverFlags.enabled());
        assertTrue(InitialPlanSolverFlags.enabled(900045L));
    }

    @Test
    void explicitOffRollsBack() {
        System.setProperty(InitialPlanSolverFlags.PROPERTY, "false");
        assertFalse(InitialPlanSolverFlags.enabled());
        assertFalse(InitialPlanSolverFlags.enabled(900045L));
    }

    @Test
    void sessionAllowlistEnablesOnlyListedSessionsWhenGlobalOff() {
        System.setProperty(InitialPlanSolverFlags.PROPERTY, "false");
        System.setProperty(InitialPlanSolverFlags.SESSIONS_PROPERTY, "900016, 10041984");

        assertTrue(InitialPlanSolverFlags.enabled(900016L));
        assertTrue(InitialPlanSolverFlags.enabled(10041984L));
        assertFalse(InitialPlanSolverFlags.enabled(900045L));
        assertFalse(InitialPlanSolverFlags.enabled());
    }

    @Test
    void globalSwitchOverridesSessionAllowlist() {
        System.setProperty(InitialPlanSolverFlags.PROPERTY, "true");
        System.setProperty(InitialPlanSolverFlags.SESSIONS_PROPERTY, "900016");
        assertTrue(InitialPlanSolverFlags.enabled(123L));
        assertTrue(InitialPlanSolverFlags.enabled());
    }
}
