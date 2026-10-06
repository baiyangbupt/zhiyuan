package com.ytell.zhiyuan.web.controller;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.base.BasePage;
import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.ProfileKVDto;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import com.ytell.zhiyuan.model.dto.UpdateScoreDetailRes;
import com.ytell.zhiyuan.model.dto.UserBasicProfileResponse;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.req.ChatMessagePageReq;
import com.ytell.zhiyuan.model.req.ChatSessionPageQuery;
import com.ytell.zhiyuan.model.req.MessageFeedbackReq;
import com.ytell.zhiyuan.model.req.UpdateTuitionRangeReq;
import com.ytell.zhiyuan.model.vo.ChatSessionVo;
import com.ytell.zhiyuan.model.vo.MessageVo;
import com.ytell.zhiyuan.service.biz.ChatMessageBizService;
import com.ytell.zhiyuan.service.biz.ChatSessionBizService;
import com.ytell.zhiyuan.service.biz.UserProfileService;
import com.ytell.zhiyuan.service.biz.VolunteerBizService;
import com.ytell.zhiyuan.model.req.UserIntentEmotionSaveReq;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/gaotu-assistant-bot/chat/{tenantId}")
@Slf4j
@Api(tags = "对话相关接口")
public class ChatController {

    @Autowired
    private ChatSessionBizService chatSessionBizService;

    @Autowired
    private ChatMessageBizService chatMessageBizService;

    @Autowired
    private UserProfileService userProfileService;

    @Autowired
    private VolunteerBizService volunteerBizService;


    /**
     * 会话相关接口
     */
    @PostMapping("/session/create")
    @ApiOperation("创建会话")
    public BaseResponse<ChatSessionVo> createChatSession(@PathVariable("tenantId") Long tenantId,
                                                         @RequestBody CreateSessionReq createSessionReq) {
        log.info("createChatSession:{}", JSONObject.toJSONString(createSessionReq));
        return BaseResponse.success(chatSessionBizService.createChatSession(tenantId, createSessionReq));
    }

    @PostMapping("/session/update-tuition-range")
    @ApiOperation("更新会话学费区间")
    public BaseResponse<Boolean> updateTuitionRange(@PathVariable("tenantId") Long tenantId,
                                                    @RequestParam("chatSessionId") Long chatSessionId,
                                                    @RequestBody UpdateTuitionRangeReq req) {
        log.info("updateTuitionRange: tenantId={}, chatSessionId={}, req={}", tenantId, chatSessionId, JSONObject.toJSONString(req));
        return BaseResponse.success(chatSessionBizService.updateTuitionRange(tenantId, chatSessionId, req.getMin(), req.getMax()));
    }

    /**
     * 空会话（draft）**同会话补录成绩**：省份/批次/选科/各科成绩/总分为必填，
     * 可另带位次/意向/优势学科。成功后会话即可走完整的候选池/推荐链路。
     *
     * <p>响应契约见 {@link UpdateScoreDetailRes}：`success` + 刷新后的 `planningVersion`
     * + `requiresWorkspaceReload`（恒 true，前端应重拉 workspace-state）。</p>
     */
    @PostMapping("/session/update-score-detail")
    @ApiOperation("空会话补录成绩")
    public BaseResponse<UpdateScoreDetailRes> updateScoreDetail(@PathVariable("tenantId") Long tenantId,
                                                                @RequestParam("chatSessionId") Long chatSessionId,
                                                                @RequestBody CreateSessionReq req) {
        log.info("updateScoreDetail: tenantId={}, chatSessionId={}, req={}",
                tenantId, chatSessionId, JSONObject.toJSONString(req));
        return BaseResponse.success(chatSessionBizService.updateScoreDetail(tenantId, chatSessionId, req));
    }

    @PostMapping("/session/page")
    @ApiOperation("对话分页列表")
    public BaseResponse<BasePage<ChatSessionVo>> pageUserSession(@PathVariable("tenantId") Long tenantId,
                                                                 @RequestBody ChatSessionPageQuery req) {
        log.info("pageUserSession:{}", JSONObject.toJSONString(req));
        return BaseResponse.success(chatSessionBizService.pageUserSession(tenantId, req));
    }

    @GetMapping("/session/detail")
    @ApiOperation("获取会话详情")
    public BaseResponse<ChatSessionVo> getUserSessionDetail(@PathVariable("tenantId") Long tenantId,
                                                            @RequestParam Long chatSessionId) {
        return BaseResponse.success(chatSessionBizService.getUserSessionDetail(tenantId, chatSessionId));
    }

    /**
     * 消息相关接口
     */

    @PostMapping("/message/page")
    @ApiOperation("分页获取对话消息")
    public BaseResponse<BasePage<MessageVo>> pageMessage(@PathVariable("tenantId") Long tenantId,
                                                         @RequestBody ChatMessagePageReq chatMessagePageReq) {
        log.info("pageMessage:{}", JSONObject.toJSONString(chatMessagePageReq));
        return BaseResponse.success(chatMessageBizService.pageMessage(tenantId, chatMessagePageReq));
    }

    @PostMapping("/message/feedback")
    @ApiOperation("更新消息反馈")
    public BaseResponse<Boolean> updateMessageFeedback(@PathVariable("tenantId") Long tenantId,
                                                       @RequestBody MessageFeedbackReq req) {
        log.info("updateMessageFeedback: tenantId={}, req={}", tenantId, JSONObject.toJSONString(req));
        return BaseResponse.success(chatMessageBizService.updateMessageFeedback(tenantId, req.getMessageId(), req.getFeedback()));
    }

    /**
     * 志愿方案相关接口
     */
    @GetMapping("/volunteer/recommend-list")
    @ApiOperation("获取志愿推荐列表")
    public BaseResponse<VolunteerRecommendListResponse> getVolunteerRecommendList(@PathVariable("tenantId") Long tenantId,
                                                                                  @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getVolunteerRecommendList: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(volunteerBizService.recommendVolunteerList(tenantId, chatSessionId,false,true));
    }

    @PostMapping("/volunteer/submit")
    @ApiOperation("提交志愿列表")
    public BaseResponse<Boolean> submitVolunteerList(@PathVariable("tenantId") Long tenantId,
                                                     @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("submitVolunteerList: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(volunteerBizService.submitVolunteerList(tenantId, chatSessionId));
    }

    @PostMapping("/volunteer/export")
    @ApiOperation("导出志愿列表")
    public ResponseEntity<ByteArrayResource> exportVolunteerList(@PathVariable("tenantId") Long tenantId,
                                                                 @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("exportVolunteerList: tenantId={}, chatSessionId={}", tenantId, chatSessionId);

        try {
            VolunteerBizService.ExcelExportResult exportResult = volunteerBizService.exportVolunteerList(tenantId, chatSessionId);

            ByteArrayResource resource = new ByteArrayResource(exportResult.getExcelData());

            HttpHeaders headers = new HttpHeaders();
            // 设置文件名，同时提供两种格式以兼容不同浏览器
            String fileName = exportResult.getFileName();
            log.info("导出Excel文件名: {}", fileName);
            
            // RFC 5987格式，支持UTF-8编码的文件名（现代浏览器）
            String encodedFileName = java.net.URLEncoder.encode(fileName, "UTF-8").replaceAll("\\+", "%20");
            // 同时设置filename和filename*，确保兼容性
            // 注意：filename放在引号中，filename*使用RFC 5987格式
            String contentDisposition = String.format("attachment; filename=\"%s\"; filename*=UTF-8''%s", 
                fileName.replace("\"", "\\\""), encodedFileName);
            headers.add(HttpHeaders.CONTENT_DISPOSITION, contentDisposition);
            headers.add(HttpHeaders.CACHE_CONTROL, "no-cache, no-store, must-revalidate");
            headers.add(HttpHeaders.PRAGMA, "no-cache");
            headers.add(HttpHeaders.EXPIRES, "0");

            return ResponseEntity.ok()
                    .headers(headers)
                    .contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                    .body(resource);

        } catch (Exception e) {
            log.error("导出志愿列表失败", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }

    /**
     * 用户信息及意向相关
     */

    @PostMapping("/user-basic-profile")
    @ApiOperation("获取用户信息-基本信息")
    public BaseResponse<UserBasicProfileResponse> userBasicProfile(@PathVariable("tenantId") Long tenantId,
                                                                   @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("userBasicProfile:chatSessionId:{}", chatSessionId);
        return BaseResponse.success(userProfileService.getUserBasicProfile(chatSessionId));
    }

    @PostMapping("/user-dynastic-profile")
    @ApiOperation("获取用户信息-意向信息")
    public BaseResponse<List<ProfileKVDto>> userDynasticProfile(@PathVariable("tenantId") Long tenantId,
                                                                @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("userDynasticProfile:chatSessionId:{}", chatSessionId);
        return BaseResponse.success(userProfileService.userDynasticProfile(chatSessionId));
    }

    @PostMapping("/user-dynastic-profile/save")
    @ApiOperation("保存用户意向情绪")
    public BaseResponse<Boolean> saveUserDynasticProfile(@PathVariable("tenantId") Long tenantId,
                                                         @RequestBody UserIntentEmotionSaveReq req) {
        log.info("saveUserDynasticProfile: tenantId={}, req={}", tenantId, JSONObject.toJSONString(req));
        return BaseResponse.success(userProfileService.saveUserIntentEmotion(req));
    }

    @PostMapping("/major-recommend")
    @ApiOperation("根据用户成绩-推荐专业")
    public BaseResponse<List<RecommendSubMajorResponse.MajorRecommendItem>> userMajorRecommend(@PathVariable("tenantId") Long tenantId,
                                                                                               @RequestBody CreateSessionReq createSessionReq) {
        log.info("userMajorRecommend:createSessionReq:{}", createSessionReq);
        return BaseResponse.success(chatSessionBizService.recommendMajor(createSessionReq));
    }

}
