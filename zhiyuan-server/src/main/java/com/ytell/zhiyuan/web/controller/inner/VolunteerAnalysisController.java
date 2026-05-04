package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.model.dto.QueryWeightDto;
import com.ytell.zhiyuan.model.dto.QueryWeightResponse;
import com.ytell.zhiyuan.model.dto.inner.MajorAnalysisReq;
import com.ytell.zhiyuan.model.dto.inner.MajorAnalysisRes;
import com.ytell.zhiyuan.model.dto.inner.SchoolAnalysisReq;
import com.ytell.zhiyuan.model.dto.inner.SchoolAnalysisRes;
import com.ytell.zhiyuan.service.biz.VolunteerAnalysisBizService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/volunteer-analysis")
@Api(tags = "内部使用接口")
public class VolunteerAnalysisController {

    @Autowired
    private VolunteerAnalysisBizService analysisBizService;


    @PostMapping("/majors")
    @ApiOperation("分析专业")
    public MajorAnalysisRes analyseMajor(
            @ApiParam("租户ID") @RequestParam Long tenantId,
            @ApiParam("会话ID") @RequestParam Long chatSessionId,
            @RequestBody MajorAnalysisReq majorAnalysisReq) {

        return analysisBizService.analyseMajor(chatSessionId, majorAnalysisReq);
    }

    @PostMapping("/schools")
    @ApiOperation("分析学校")
    public SchoolAnalysisRes analyseSchool(
            @ApiParam("租户ID") @RequestParam Long tenantId,
            @ApiParam("会话ID") @RequestParam Long chatSessionId,
            @RequestBody SchoolAnalysisReq schoolAnalysisReq) {

        return analysisBizService.analyseSchool(chatSessionId, schoolAnalysisReq);
    }

    @PostMapping("/query-weight")
    @ApiOperation("查询权重")
    public QueryWeightResponse queryWeight(
            @ApiParam("租户ID") @RequestParam Long tenantId,
            @ApiParam("会话ID") @RequestParam Long chatSessionId,
            @RequestBody QueryWeightDto queryinfo) {

        return analysisBizService.queryWeight(tenantId, chatSessionId, queryinfo);
    }


}
