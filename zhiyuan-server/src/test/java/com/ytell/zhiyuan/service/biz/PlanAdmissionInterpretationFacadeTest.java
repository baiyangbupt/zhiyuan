package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationReq;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.InterpretationEntryDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.doReturn;

class PlanAdmissionInterpretationFacadeTest {

    private PlanAdmissionInterpretationFacade facade;
    private PlanningStateService planningStateService;

    @BeforeEach
    void setUp() {
        facade = new PlanAdmissionInterpretationFacade();
        planningStateService = Mockito.mock(PlanningStateService.class);
        ReflectionTestUtils.setField(facade, "planningStateService", planningStateService);
    }

    @Test
    void missingPlanVersionIsRejected() {
        BusinessException error = assertThrows(BusinessException.class,
                () -> facade.interpret(1L, 2L, new AdmissionInterpretationReq()));
        assertEquals(400, error.getStatus());
        assertEquals(PlanAdmissionInterpretationFacade.PLAN_VERSION_REQUIRED, error.getMessage());
    }

    @Test
    void versionMismatchIsStaleInterpretation() {
        PlanningStateDTO state = stateWithPlan();
        state.setVersion(9);
        doReturn(state).when(planningStateService).loadPlanningStateReadOnly(2L);

        AdmissionInterpretationReq req = new AdmissionInterpretationReq();
        req.setPlanVersion(8);

        BusinessException error = assertThrows(BusinessException.class,
                () -> facade.interpret(1L, 2L, req));
        assertEquals(409, error.getStatus());
        assertEquals(PlanAdmissionInterpretationFacade.STALE_INTERPRETATION, error.getMessage());
    }

    @Test
    void groupModeBuildsUnitEntriesAndInterpretation() {
        PlanningStateDTO state = stateWithPlan();
        doReturn(state).when(planningStateService).loadPlanningStateReadOnly(2L);

        AdmissionInterpretationReq req = new AdmissionInterpretationReq();
        req.setPlanVersion(7);

        AdmissionInterpretationRes res = facade.interpret(1L, 2L, req);

        assertEquals(AdmissionInterpretationRes.STATUS_COMPLETED, res.getStatus());
        assertEquals("major_group", res.getAdmissionMode());
        assertEquals(3, res.getScenarios().size());
        assertTrue(res.getBaseLanding() != null);
        assertEquals("base", res.getBaseLanding().getLabel());
    }

    @Test
    void buildEntriesJoinsCandidateRatiosInMajorMode() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId("v1");
        candidate.setSchoolEnrollRatio(40D);
        candidate.setAdmissionRatio(35D);
        state.getCandidatePoolState().getItems().add(candidate);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        item.setPosition(1);
        item.setTier("冲");
        item.setSchoolName("A大学");
        item.setMajorName("计算机");
        state.getOrderedPlanState().getItems().add(item);

        List<InterpretationEntryDTO> entries =
                PlanAdmissionInterpretationFacade.buildEntries(state, false);

        assertEquals(1, entries.size());
        assertEquals("volunteer", entries.get(0).getLevel());
        assertEquals("v1", entries.get(0).getId());
        assertEquals(40D, entries.get(0).getSchoolRatio());
        assertEquals(35D, entries.get(0).getMajorRatio());
    }

    @Test
    void shouldTreatBothMajorGroupSpellingsAsGroupMode() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        assertTrue(PlanAdmissionInterpretationFacade.isMajorGroupMode(state));

        state.getCandidatePoolState().setVolunteerModel("major_group");
        assertTrue(PlanAdmissionInterpretationFacade.isMajorGroupMode(state));

        state.getCandidatePoolState().setVolunteerModel("major");
        assertFalse(PlanAdmissionInterpretationFacade.isMajorGroupMode(state));
    }

    private PlanningStateDTO stateWithPlan() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setItems(Lists.newArrayList());

        OrderedUnitDTO first = new OrderedUnitDTO();
        first.setUnitId("u1");
        first.setPosition(1);
        first.setSchoolName("A大学第01组");
        first.setTier("冲");
        first.setSchoolEnrollRatio(45D);
        first.setAdmissionRatio(42D);
        first.getMajorItems().add(major("v1"));

        OrderedUnitDTO second = new OrderedUnitDTO();
        second.setUnitId("u2");
        second.setPosition(2);
        second.setSchoolName("B大学第01组");
        second.setTier("稳");
        second.setSchoolEnrollRatio(62D);
        second.setAdmissionRatio(60D);
        second.getMajorItems().add(major("v2"));

        state.getOrderedPlanState().getUnits().add(first);
        state.getOrderedPlanState().getUnits().add(second);
        return state;
    }

    private PlanningUnitMajorDTO major(String volunteerId) {
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        major.setMajorName("计算机");
        return major;
    }
}
