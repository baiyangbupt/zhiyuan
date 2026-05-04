package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.model.dto.RecommendReq;
import com.ytell.zhiyuan.model.dto.inner.MajorRecommendResponse;
import com.ytell.zhiyuan.model.dto.inner.SchoolRecommendResponse;
import com.ytell.zhiyuan.model.dto.inner.SimulateDiffRequest;
import com.ytell.zhiyuan.model.dto.inner.SimulateDiffResponse;
import com.ytell.zhiyuan.service.biz.ChatSessionBizService;
import com.ytell.zhiyuan.service.biz.VolunteerBizService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/recommend")
@Api(tags = "内部使用接口")
public class RecommendController {

    @Autowired
    private VolunteerBizService volunteerBizService;
    @Autowired
    private ChatSessionBizService chatSessionBizService;

    @GetMapping("/schoolMajors")
    @ApiOperation("推荐学校专业")
    public SchoolRecommendResponse recommendSchoolMajors(
            @ApiParam("租户ID") @RequestParam Long tenantId,
            @ApiParam("会话ID") @RequestParam Long chatSessionId,
            @ApiParam(value = "是否使用截断逻辑", defaultValue = "true") @RequestParam(defaultValue = "true") Boolean useTruncatedLogic) {
        
        return volunteerBizService.recommendSchoolMajors(tenantId, chatSessionId, useTruncatedLogic);
    }

    @PostMapping("/school-major")
    @ApiOperation("推荐学校专业")
    public SchoolRecommendResponse recommendSchoolMajor(
            @ApiParam("租户ID") @RequestParam Long tenantId,
            @ApiParam("会话ID") @RequestParam Long chatSessionId,
            @RequestBody RecommendReq recommendReq
    ) {

        return volunteerBizService.recommendSchoolMajor(tenantId, chatSessionId, recommendReq);
    }

    @GetMapping("/majors")
    @ApiOperation("推荐专业类")
    public MajorRecommendResponse recommendMajors(
            @ApiParam("租户ID") @RequestParam Long tenantId,
            @ApiParam("会话ID") @RequestParam Long chatSessionId) {
        MajorRecommendResponse response=new MajorRecommendResponse();
        response.setMajorList(chatSessionBizService.recommendMajor(chatSessionId));
        return response;
    }

    @PostMapping("/simulate-diff")
    @ApiOperation("模拟画像变更对志愿方案的影响")
    public SimulateDiffResponse simulateDiff(
            @ApiParam("租户ID") @RequestParam Long tenantId,
            @ApiParam("会话ID") @RequestParam Long chatSessionId,
            @RequestBody SimulateDiffRequest request) {
        return volunteerBizService.simulateDiff(tenantId, chatSessionId, request);
    }
}
