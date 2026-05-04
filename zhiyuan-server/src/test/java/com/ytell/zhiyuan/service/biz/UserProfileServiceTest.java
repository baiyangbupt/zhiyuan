package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateVersionDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.req.UserIntentEmotionSaveReq;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class UserProfileServiceTest {

    private UserProfileService userProfileService;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private VolunteerUtils volunteerUtils;
    private VolunteerDataProvider volunteerDataProvider;
    private PlanningStateService planningStateService;

    @BeforeEach
    void setUp() {
        userProfileService = new UserProfileService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        volunteerUtils = Mockito.mock(VolunteerUtils.class);
        volunteerDataProvider = Mockito.mock(VolunteerDataProvider.class);
        planningStateService = Mockito.mock(PlanningStateService.class);

        ReflectionTestUtils.setField(userProfileService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(userProfileService, "utils", volunteerUtils);
        ReflectionTestUtils.setField(userProfileService, "dataProvider", volunteerDataProvider);
        ReflectionTestUtils.setField(userProfileService, "planningStateService", planningStateService);
    }

    @Test
    void shouldSyncPlanningProfileWhenSaveUserIntentEmotion() {
        UserProfileData originProfile = new UserProfileData();
        originProfile.getCity_info().setProvince(java.util.Arrays.asList("北京"));
        originProfile.getCity_info().setProvince_emotion(java.util.Arrays.asList("Strong"));

        when(volunteerDataProvider.getUserProfileData(1L)).thenReturn(originProfile);
        when(volunteerUtils.mergeUserProfile(originProfile)).thenReturn(originProfile);

        CreateSessionReq scoreDetail = new CreateSessionReq();
        when(volunteerDataProvider.getUserScoreDetail(1L)).thenReturn(scoreDetail);

        ChatSessionExtraData extraData = new ChatSessionExtraData();
        extraData.setChatSessionId(1L);
        extraData.setDataKey("userprofile");
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq("userprofile"))).thenReturn(extraData);

        PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
        versionDTO.setVersion(3);
        versionDTO.setStaleFlags(new com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO());
        versionDTO.getStaleFlags().setRecommendationOverlay(true);
        versionDTO.getStaleFlags().setOrderedPlan(true);
        versionDTO.getStaleFlags().setReview(true);
        when(planningStateService.syncProfileStateFromLegacy(eq(1L), eq(scoreDetail), eq(originProfile), eq(true)))
                .thenReturn(versionDTO);

        UserIntentEmotionSaveReq req = new UserIntentEmotionSaveReq();
        req.setChatSessionId(1L);
        UserIntentEmotionSaveReq.IntentEmotionItem item = new UserIntentEmotionSaveReq.IntentEmotionItem();
        item.setDimension("cityProvince");
        item.setPolarity("POSITIVE");
        item.setLabel("上海");
        item.setEmotion("Strong");
        req.setIntents(java.util.Arrays.asList(item));

        Boolean result = userProfileService.saveUserIntentEmotion(req);

        assertTrue(result);
        assertEquals(java.util.Arrays.asList("北京", "上海"), originProfile.getCity_info().getProvince());

        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService).updateById(captor.capture());
        assertTrue(captor.getValue().getDataValue().contains("上海"));
        verify(planningStateService).syncProfileStateFromLegacy(1L, scoreDetail, originProfile, true);
    }
}
