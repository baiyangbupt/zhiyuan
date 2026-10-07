package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.ApplyTypeUtil;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 志愿数据提供者
 * 负责获取和提供志愿相关的各种数据
 */
@Slf4j
@Service
public class VolunteerDataProvider {

    @Autowired
    private ChatSessionSharedService chatSessionSharedService;

    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;

    @Autowired
    private ChatSessionBizService chatSessionBizService;

    /**
     * 获取会话信息
     */
    public ChatSession getChatSession(Long chatSessionId) {
        ChatSession chatSession = chatSessionSharedService.getById(chatSessionId);
        if (chatSession == null) {
            throw new BusinessException(404, "会话不存在");
        }
        return chatSession;
    }

    /**
     * 获取用户分数信息
     */
    public CreateSessionReq getUserScoreDetail(Long chatSessionId) {
        ChatSessionExtraData chatSessionExtraDataScore = chatSessionExtraDataSharedService
                .getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (chatSessionExtraDataScore == null) {
            throw new BusinessException(404, "用户分数信息不存在");
        }
        return JSONObject.parseObject(chatSessionExtraDataScore.getDataValue(), CreateSessionReq.class);
    }

    /**
     * 获取用户画像数据
     */
    public UserProfileData getUserProfileData(Long chatSessionId) {
        ChatSessionExtraData chatSessionExtraDataUserProfile = chatSessionExtraDataSharedService
                .getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        if (chatSessionExtraDataUserProfile != null && chatSessionExtraDataUserProfile.getDataValue() != null) {
            return JSONObject.parseObject(chatSessionExtraDataUserProfile.getDataValue(), UserProfileData.class);
        }
        return null;
    }

    /**
     * 获取用户初始画像数据
     */
    public UserProfileData getUserInitProfile(Long chatSessionId) {
        ChatSessionExtraData chatSessionExtraDataUserInitProfile = chatSessionExtraDataSharedService
                .getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_INIT_PROFILE_KEY);
        if (chatSessionExtraDataUserInitProfile != null && chatSessionExtraDataUserInitProfile.getDataValue() != null) {
            return JSONObject.parseObject(chatSessionExtraDataUserInitProfile.getDataValue(), UserProfileData.class);
        }
        return null;
    }

    /**
     * 获取志愿全量数据
     */
    public VolunteerDataDTO getVolunteerDataDTO(Long chatSessionId) {
        return chatSessionBizService.loadChatSessionVolunteerData(chatSessionId);
    }

    /**
     * 获取格式化的全量志愿数据
     * @param volunteerDataDTO
     * @return
     */
    public List<VolunteerSchoolGroup> transformToVolunteerSchoolGroups(VolunteerDataDTO volunteerDataDTO) {
        return chatSessionBizService.transformToVolunteerSchoolGroups(volunteerDataDTO);
    }

    /**
     * 获取志愿数据类型编码
     */
    public String getApplyTypeCode(VolunteerDataDTO volunteerDataDTO) {
        return volunteerDataDTO.getType().getCode();
    }

    /**
     * 计算目标学校数量。
     *
     * <p>成绩行缺 {@code volunteerCount}（老会话/legacy 草稿，未补录填报数量）时返回
     * {@code null}，由调用方退化成"0 配额"继续跑——以前这里直接解引用
     * {@code getVolunteerCount().getMajorCount()}，会 NPE 成 {@code code -1"系统错误"}
     * （实测 10041966：{@code generateInitialPlan → refreshRecommendationOverlay →
     * recommendVolunteerList → prepareVolunteerData → calculateTargetSchoolCount}）。</p>
     */
    public Integer calculateTargetSchoolCount(CreateSessionReq userScoreDetail, String applyType) {
        if (userScoreDetail == null || userScoreDetail.getVolunteerCount() == null) {
            log.warn("calculateTargetSchoolCount skipped reason=volunteer_count_missing applyType={}", applyType);
            return null;
        }
        if (ApplyTypeUtil.isMajorSchoolType(applyType)) {
            return userScoreDetail.getVolunteerCount().getMajorCount();
        } else {
            return userScoreDetail.getVolunteerCount().getSchoolCount();
        }
    }
}
