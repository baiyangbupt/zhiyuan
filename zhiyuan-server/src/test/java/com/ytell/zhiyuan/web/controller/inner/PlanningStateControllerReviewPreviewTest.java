package com.ytell.zhiyuan.web.controller.inner;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.config.GlobalExceptionHandler;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.RecommendationOverlayStateDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.service.biz.PendingConfirmationBizService;
import com.ytell.zhiyuan.service.biz.PlanningStateService;
import com.ytell.zhiyuan.service.biz.VolunteerBizService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class PlanningStateControllerReviewPreviewTest {
    private MockMvc mockMvc;
    private ChatSessionExtraDataSharedService storage;
    private VolunteerBizService volunteerService;
    private PendingConfirmationBizService pendingService;
    private ChatSessionExtraData row;
    private PlanningStateDTO state;

    @BeforeEach
    void setUp() {
        storage = mock(ChatSessionExtraDataSharedService.class);
        volunteerService = mock(VolunteerBizService.class);
        pendingService = mock(PendingConfirmationBizService.class);
        PlanningStateService service = new PlanningStateService();
        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", storage);
        ReflectionTestUtils.setField(service, "volunteerBizService", volunteerService);
        ReflectionTestUtils.setField(service, "pendingConfirmationBizService", pendingService);
        PlanningStateController controller = new PlanningStateController();
        ReflectionTestUtils.setField(controller, "planningStateService", service);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .setMessageConverters(new MappingJackson2HttpMessageConverter(new ObjectMapper())).build();

        state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId("school1_major1");
        candidate.setSchoolName("学校一");
        candidate.setMajorName("专业一");
        candidate.setTier("sprint");
        candidate.setAdmissionRatio(50D);
        candidate.setProvinceName("浙江");
        state.getCandidatePoolState().setItems(Lists.newArrayList(candidate));
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(candidate.getVolunteerId());
        item.setPosition(1);
        item.setTier("sprint");
        state.getOrderedPlanState().setItems(Lists.newArrayList(item));
        RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
        overlay.setVolunteerId(candidate.getVolunteerId());
        state.getRecommendationOverlayState().setItems(Lists.newArrayList(overlay));
        state.getStaleFlags().setReview(true);
        row = new ChatSessionExtraData();
        when(storage.getBySessionIdAndDataKey(101L, ChatSessionExtraDataConstants.PLANNING_STATE_KEY)).thenReturn(row);
        storeFixture();
    }

    @Test
    void returnsFreshTypedFindingsWithoutPersistingReviewOverlayOrPending() throws Exception {
        String baseline = row.getDataValue();
        MvcResult result = preview().andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("preview_only"))
                .andExpect(jsonPath("$.data.sourceVersion").value(7))
                .andExpect(jsonPath("$.data.review.evaluationStatus").value("completed"))
                .andExpect(jsonPath("$.data.review.sourceVersion").value(7))
                .andExpect(jsonPath("$.data.proposals").isEmpty()).andReturn();
        JSONObject review = JSON.parseObject(result.getResponse().getContentAsString()).getJSONObject("data").getJSONObject("review");
        JSONObject count = review.getJSONArray("findings").stream().map(value -> (JSONObject) value)
                .filter(value -> "count_validation_hard".equals(value.getString("code"))).findFirst().get();
        assertEquals("fail", count.getString("resultStatus"));
        assertEquals(2, count.getJSONObject("suggestedCommand").getInteger("targetCount"));
        assertFalse(count.getJSONObject("suggestedCommand").getBooleanValue("executable"));
        assertEquals(baseline, row.getDataValue());
        assertReadOnly();
    }

    @Test
    void repeatedPreviewsKeepEvaluationAndCommandDigestsStable() throws Exception {
        String first = preview().andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        String second = preview().andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        JSONObject firstReview = JSON.parseObject(first).getJSONObject("data").getJSONObject("review");
        JSONObject secondReview = JSON.parseObject(second).getJSONObject("data").getJSONObject("review");
        assertNotNull(firstReview.getString("evaluationVersion"));
        assertEquals(firstReview.getString("evaluationVersion"), secondReview.getString("evaluationVersion"));
        assertEquals(firstReview.getJSONArray("findings"), secondReview.getJSONArray("findings"));
        assertReadOnly();
    }

    @Test
    void staleOverlayFailsClosedInsteadOfRefreshingAndPersistingIt() throws Exception {
        state.getStaleFlags().setRecommendationOverlay(true);
        storeFixture();
        preview().andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value(40905))
                .andExpect(jsonPath("$.msg").value("review_fix_stale"));
        assertReadOnly();
    }

    @Test
    void staleCandidateFactsFailClosedWithoutWriting() throws Exception {
        state.getStaleFlags().setCandidatePool(true);
        storeFixture();
        preview().andExpect(status().isConflict());
        assertReadOnly();
    }

    @Test
    void missingStateDoesNotImportOrPersistLegacyState() throws Exception {
        when(storage.getBySessionIdAndDataKey(101L, ChatSessionExtraDataConstants.PLANNING_STATE_KEY)).thenReturn(null);
        preview().andExpect(status().isConflict());
        assertReadOnly();
    }

    @Test
    void missingOverlayFailsClosedWithoutCreatingAnOverlay() throws Exception {
        state.getRecommendationOverlayState().getItems().clear();
        storeFixture();
        preview().andExpect(status().isConflict())
                .andExpect(jsonPath("$.msg").value("review_fix_stale"));
        assertReadOnly();
    }

    @Test
    void readsSplitCandidatePoolWithoutBackfillWrites() throws Exception {
        ChatSessionExtraData poolRow = new ChatSessionExtraData();
        poolRow.setDataValue(JSON.toJSONString(state.getCandidatePoolState()));
        when(storage.getBySessionIdAndDataKey(101L, ChatSessionExtraDataConstants.PLANNING_CANDIDATE_POOL_KEY))
                .thenReturn(poolRow);
        state.getCandidatePoolState().getItems().clear();
        JSONObject stored = (JSONObject) JSON.toJSON(state);
        stored.put("candidatePoolRef", new JSONObject());
        row.setDataValue(stored.toJSONString());
        String baseline = row.getDataValue();

        preview().andExpect(status().isOk())
                .andExpect(jsonPath("$.data.review.evaluationStatus").value("completed"));

        assertEquals(baseline, row.getDataValue());
        verify(storage).getBySessionIdAndDataKey(101L, ChatSessionExtraDataConstants.PLANNING_CANDIDATE_POOL_KEY);
        assertReadOnly();
    }

    @Test
    void previewsFrozenProbabilityOrderWithFreshPreflightAndNoPendingOrWrites() throws Exception {
        prepareInversionFixture();
        String baseline = row.getDataValue();
        String first = preview().andExpect(status().isOk())
                .andExpect(jsonPath("$.data.proposals[0].status").value("preview_only"))
                .andExpect(jsonPath("$.data.proposals[0].requiresConfirmation").value(false))
                .andExpect(jsonPath("$.data.proposals[0].findingPostcondition.satisfied").value(true))
                .andExpect(jsonPath("$.data.proposals[0].frozenReviewPlan.orderedEntityIds[0]").value("low"))
                .andExpect(jsonPath("$.data.proposals[0].frozenReviewPlan.orderedEntityIds[2]").value("high"))
                .andReturn().getResponse().getContentAsString();
        String second = preview().andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        assertEquals(JSON.parseObject(first).getJSONObject("data").getJSONArray("proposals"),
                JSON.parseObject(second).getJSONObject("data").getJSONArray("proposals"));
        assertEquals(baseline, row.getDataValue());
        assertReadOnly();
    }

    @Test
    void noFrozenRepairWhenSortingLeavesHardSafetyShortfall() throws Exception {
        prepareInversionFixture();
        state.getWorkingPlanState().getItems().forEach(item -> item.setTier("sprint"));
        state.getOrderedPlanState().getItems().forEach(item -> item.setTier("sprint"));
        state.getCandidatePoolState().getItems().forEach(item -> item.setTier("sprint"));
        storeFixture();
        preview().andExpect(status().isOk())
                .andExpect(jsonPath("$.data.proposals[0].findingPostcondition.satisfied").value(false))
                .andExpect(jsonPath("$.data.proposals[0].blockingReason").value("hard_constraints_unsatisfied"))
                .andExpect(jsonPath("$.data.proposals[0].frozenReviewPlan").doesNotExist());
        assertReadOnly();
    }

    @Test
    void noFrozenRepairWhenIdOnlyHardConstraintCannotBeEvaluated() throws Exception {
        prepareInversionFixture();
        state.getConstraintState().getHardConstraints().getMustIncludeMajorIds().add("required-major-id");
        storeFixture();
        preview().andExpect(status().isOk())
                .andExpect(jsonPath("$.data.proposals[0].blockingReason").value("review_fix_facts_incomplete"))
                .andExpect(jsonPath("$.data.proposals[0].frozenReviewPlan").doesNotExist());
        assertReadOnly();
    }

    private void prepareInversionFixture() {
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().getItems().clear();
        state.getOrderedPlanState().getItems().clear();
        state.getWorkingPlanState().getItems().clear();
        state.getRecommendationOverlayState().getItems().clear();
        String[] identities = {"high", "mid", "low"};
        double[] ratios = {90D, 60D, 30D};
        for (int index = 0; index < identities.length; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(identities[index]);
            candidate.setAdmissionRatio(ratios[index]);
            candidate.setSchoolEnrollRatio(ratios[index]);
            candidate.setTier("protect");
            candidate.setProvinceName("浙江");
            state.getCandidatePoolState().getItems().add(candidate);
            DraftItemDTO selected = new DraftItemDTO();
            selected.setVolunteerId(identities[index]);
            selected.setTier("protect");
            state.getWorkingPlanState().getItems().add(selected);
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId(identities[index]);
            item.setTier("protect");
            item.setPosition(index + 1);
            state.getOrderedPlanState().getItems().add(item);
            RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
            overlay.setVolunteerId(identities[index]);
            state.getRecommendationOverlayState().getItems().add(overlay);
        }
        storeFixture();
    }

    private org.springframework.test.web.servlet.ResultActions preview() throws Exception {
        return mockMvc.perform(post("/gaotu-assistant-bot/inner/planning/7/session/fix-proposals/preview")
                .param("chatSessionId", "101"));
    }

    private void storeFixture() {
        row.setDataValue(JSON.toJSONString(state));
    }

    private void assertReadOnly() {
        assertTrue(mockingDetails(storage).getInvocations().stream()
                .allMatch(invocation -> "getBySessionIdAndDataKey".equals(invocation.getMethod().getName())));
        verifyNoInteractions(volunteerService, pendingService);
    }
}
