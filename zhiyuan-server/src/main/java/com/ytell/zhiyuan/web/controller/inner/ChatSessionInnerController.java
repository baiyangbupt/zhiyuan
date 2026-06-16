package com.ytell.zhiyuan.web.controller.inner;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Splitter;
import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.SaveMessageRes;
import com.ytell.zhiyuan.model.dto.inner.ChatSessionExtraDataReq;
import com.ytell.zhiyuan.model.dto.inner.MajorSubjectAvailReq;
import com.ytell.zhiyuan.model.dto.inner.PlanParamAvailReq;
import com.ytell.zhiyuan.model.req.UpdateTuitionRangeReq;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.vo.ChatSessionExtraDataVo;
import com.ytell.zhiyuan.model.vo.MessageVo;
import com.ytell.zhiyuan.service.biz.ChatMessageBizService;
import com.ytell.zhiyuan.service.biz.ChatSessionBizService;
import com.ytell.zhiyuan.service.biz.PlanValidationService;
import com.ytell.zhiyuan.service.biz.VolunteerBizService;
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
import java.util.Map;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/chat/{tenantId}")
@Slf4j
@Api(tags = "内部使用接口")
public class ChatSessionInnerController {
    @Autowired
    private ChatMessageBizService chatMessageBizService;
    @Autowired
    private ChatSessionBizService chatSessionBizService;
    @Autowired
    private PlanValidationService planValidationService;
    @Autowired
    private VolunteerBizService volunteerBizService;

    @GetMapping("/message/list-all")
    @ApiOperation("获取全部对话消息")
    public BaseResponse<List<MessageVo>> listAll(@PathVariable("tenantId") Long tenantId,
                                                 @RequestParam Long chatSessionId) {
        return BaseResponse.success(chatMessageBizService.listAll(tenantId, chatSessionId));
    }

    @PostMapping("/message/save")
    @ApiOperation("保存对话消息")
    public BaseResponse<SaveMessageRes> saveMessage(@PathVariable("tenantId") Long tenantId,
                                                    @RequestBody MessageVo messageVo) {
        log.info("saveMessage:{}", JSONObject.toJSONString(messageVo));
        return BaseResponse.success(chatMessageBizService.saveOrUpdate(tenantId, messageVo));
    }

    @GetMapping("/message/get-by-id")
    @ApiOperation("获取一条对话")
    public BaseResponse<MessageVo> getMessageById(@PathVariable("tenantId") Long tenantId,
                                                  @RequestParam Long messageId) {
        log.info("getMessageById:{}", messageId);
        return BaseResponse.success(chatMessageBizService.getMessageById(tenantId, messageId));
    }

    @PostMapping("/session/add-extra-data")
    @ApiOperation("添加额外数据")
    public BaseResponse<ChatSessionExtraData> addSessionExtraData(@PathVariable("tenantId") Long tenantId,
                                                                  @RequestBody
                                                                  ChatSessionExtraDataReq extraDataReq) {
        log.info("addSessionExtraData:filterReq:{}", JSONObject.toJSONString(extraDataReq));
        return BaseResponse.success(chatSessionBizService.addOrUpdateSessionExtraData(tenantId, extraDataReq));
    }

    @PostMapping("/session/update-tuition-range")
    @ApiOperation("内部更新会话学费区间")
    public BaseResponse<Boolean> updateTuitionRange(@PathVariable("tenantId") Long tenantId,
                                                    @RequestParam("chatSessionId") Long chatSessionId,
                                                    @RequestBody UpdateTuitionRangeReq req) {
        log.info("updateTuitionRange(inner): tenantId={}, chatSessionId={}, req={}", tenantId, chatSessionId, JSONObject.toJSONString(req));
        return BaseResponse.success(chatSessionBizService.updateTuitionRange(tenantId, chatSessionId, req.getMin(), req.getMax()));
    }

    @GetMapping("/session/get-extra-data")
    @ApiOperation("获取额外数据")
    public BaseResponse<Map<String, Object>> getSessionExtraData(@PathVariable("tenantId") Long tenantId,
                                                                 @RequestParam("chatSessionId") Long chatSessionId,
                                                                 @RequestParam("keyList") String keyList,
                                                                 @RequestParam(value = "version", defaultValue = "0", required = false) Integer version
    ) {
        log.info("getSessionExtraData:chatSessionId:{},keyList:{},version:{}", chatSessionId, keyList, version);
        List<String> keys = Splitter.on(",").splitToList(keyList);
        return BaseResponse.success(chatSessionBizService.getSessionExtraDataByKeyListWithVersion(tenantId, chatSessionId, keys, version));
    }

    @GetMapping("/session/get-extra-data-last-version")
    @ApiOperation("获取额外数据")
    public BaseResponse<ChatSessionExtraDataVo> getSessionExtraDataLastVersion(@PathVariable("tenantId") Long tenantId,
                                                                               @RequestParam("chatSessionId") Long chatSessionId,
                                                                               @RequestParam("key") String key
    ) {
        log.info("getSessionExtraDataLastVersion:chatSessionId:{},key:{},version:{}", chatSessionId, key);
        return BaseResponse.success(chatSessionBizService.getSessionExtraDataLastVersion(tenantId, chatSessionId, key));
    }

    @GetMapping("/session/list-extra-data-by-version")
    @ApiOperation("获取额外数据多个版本")
    public BaseResponse<List<ChatSessionExtraDataVo>> listSessionExtraData(@PathVariable("tenantId") Long tenantId,
                                                                           @RequestParam("chatSessionId") Long chatSessionId,
                                                                           @RequestParam("key") String key,
                                                                           @RequestParam(value = "versionList", defaultValue = "0", required = false) String versionList
    ) {
        log.info("listSessionExtraData:chatSessionId:{},key:{},version:{}", chatSessionId, key, versionList);
        List<String> versions = Splitter.on(",").splitToList(versionList);
        List<Integer> verisonList = versions.stream().map(Integer::valueOf).collect(Collectors.toList());
        return BaseResponse.success(chatSessionBizService.listSessionExtraDataByKeyAndVersions(tenantId, chatSessionId, key, verisonList));
    }

    @PostMapping("/plan/param/avail")
    @ApiOperation("根据全量方案判断学生的志愿诉求能否满足")
    public BaseResponse<Boolean> checkPlanParamAvailability(@PathVariable("tenantId") Long tenantId,
                                                            @RequestBody PlanParamAvailReq req) {
        log.info("checkPlanParamAvailability: tenantId={}, req={}", tenantId, JSONObject.toJSONString(req));

        boolean result = planValidationService.checkPlanParamAvailability(tenantId, req);
        return BaseResponse.success(result);
    }

    @PostMapping("/plan/major/subject/avail")
    @ApiOperation("根据学生选课判断能否填报相关专业")
    public BaseResponse<Boolean> checkMajorSubjectAvailability(@PathVariable("tenantId") Long tenantId,
                                                               @RequestBody MajorSubjectAvailReq req) {
        log.info("checkMajorSubjectAvailability: tenantId={}, req={}", tenantId, JSONObject.toJSONString(req));
        boolean result = planValidationService.checkMajorSubjectAvailability(tenantId, req);
        return BaseResponse.success(result);
    }

    @PostMapping("/session/load-volunteer-format-data")
    @ApiOperation("获取志愿全量数据")
    public BaseResponse<List<VolunteerSchoolGroup>> loadSessionVolunteerFormatData(@PathVariable("tenantId") Long tenantId, @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("loadSessionVolunteerFormatData: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(chatSessionBizService.loadSessionVolunteerFormatData(chatSessionId));
    }

    @PostMapping("/volunteer/submit")
    @ApiOperation("提交志愿列表")
    public BaseResponse<Boolean> submitVolunteerList(@PathVariable("tenantId") Long tenantId,
                                                     @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("submitVolunteerList(inner): tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(volunteerBizService.submitVolunteerList(tenantId, chatSessionId));
    }

    @PostMapping("/volunteer/export")
    @ApiOperation("导出志愿列表")
    public ResponseEntity<ByteArrayResource> exportVolunteerList(@PathVariable("tenantId") Long tenantId,
                                                                 @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("exportVolunteerList(inner): tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        try {
            VolunteerBizService.ExcelExportResult exportResult = volunteerBizService.exportVolunteerList(tenantId, chatSessionId);
            ByteArrayResource resource = new ByteArrayResource(exportResult.getExcelData());

            HttpHeaders headers = new HttpHeaders();
            String fileName = exportResult.getFileName();
            log.info("exportVolunteerList(inner) fileName: {}", fileName);

            String encodedFileName = java.net.URLEncoder.encode(fileName, "UTF-8").replaceAll("\\+", "%20");
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
            log.error("exportVolunteerList(inner) failed", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }




}
