package com.ytell.zhiyuan.web.controller.inner;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.gaotu.*;
import com.ytell.zhiyuan.model.dto.gaotu.req.*;
import com.ytell.zhiyuan.model.dto.gaotu.res.QueryProgramByLimitNumRes;
import com.ytell.zhiyuan.model.dto.gaotu.res.QuerySchoolMajorScoreLineRes;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@Slf4j
@RestController
@RequestMapping("/gaotu-assistant-bot/inner/gaotu")
@Api(tags = "内部使用接口")
public class GaotuClientDebugController {

    @Autowired
    private GaotuClient gaotuClient;

    @GetMapping("/member/id")
    @ApiOperation("根据sid获取用户ID")
    public Long getMemberId(@ApiParam("用户SID") @RequestParam String customerId) {
        return gaotuClient.getMemberId(customerId);
    }

    @GetMapping("/member/score")
    @ApiOperation("获取用户成绩信息")
    public ResponseDTO<MemberScoreDetailDTO> getMemberScore(@ApiParam("用户ID") @RequestParam Long memberId, @ApiParam("用户ID") @RequestParam(required = false) Long formId) {
        return gaotuClient.getMemberScore(memberId, formId);
    }

    @GetMapping("/batch/info")
    @ApiOperation("获取批次线数据")
    public ResponseDTO<BatchDataResponseDTO> getBatchList(
            @ApiParam("地区ID") @RequestParam Long areaId,
            @ApiParam("准备类型") @RequestParam String prepareType,
            @ApiParam("科目") @RequestParam String subject,
            @ApiParam("租户ID，证据签发范围") @RequestParam(required = false) Long tenantId,
            @ApiParam("会话ID，证据签发范围") @RequestParam(required = false) Long chatSessionId,
            @ApiParam("线程ID，证据签发范围") @RequestParam(required = false) String threadId) {
        return gaotuClient.getBatchList(areaId, prepareType, subject,
                EvidenceScope.of(tenantId, chatSessionId, threadId));
    }

    @PostMapping("/report/info")
    @ApiOperation("获取报告信息")
    public ResponseDTO<GetReportInfoDTO> getReportInfo(@RequestBody GetReportInfoReq req) {
        return gaotuClient.getReportInfo(req);
    }

    @PostMapping("/report/list")
    @ApiOperation("获取报告列表")
    public ResponseDTO<ListReportInfoDTO> getReportList(@RequestBody ListReportInfoRpcReq req) {
        return gaotuClient.getReportList(req);
    }

    @PostMapping("/program/list")
    @ApiOperation("获取志愿方案列表")
    public ResponseDTO<ProgramPageDTO> getProgramList(@RequestBody ProgramPageReq req) {
        return gaotuClient.getProgramList(req);
    }

    @PostMapping("/program/full-list")
    @ApiOperation("获取志愿方案列表-最新全量")
    public ResponseDTO<JSONObject> getProgramFullList(@RequestBody ProgramPageReq req) {
        return gaotuClient.getProgramFullList(req);
    }

    @PostMapping("/program/save")
    @ApiOperation("保存志愿方案")
    public ResponseDTO<Long> saveProgramInfo(@RequestBody VolunteerProgramSaveDTO req) {
        return gaotuClient.saveProgramInfo(req);
    }

    @PostMapping("/form/delete")
    @ApiOperation("删除用户分数表格")
    public ResponseDTO<Boolean> deleteUserScoreForm(@RequestParam("formId") Long formId,
                                                    @RequestParam("memberId") Long memberId) {
        return gaotuClient.deleteUserScoreForm(formId, memberId);
    }

    @PostMapping("/score/position-range")
    @ApiOperation("根据分数获取位次范围")
    public ResponseDTO<ScorePositionRangeRes> getScorePositionRange(@RequestBody ScorePositionRangeReq req) {
        return gaotuClient.getScorePositionRange(req);
    }

    @PostMapping("/program/recommend-num")
    @ApiOperation("获取省填报数量要求")
    public ResponseDTO<RecommendNumResponse> getRecommendProgramNum(@RequestBody RecommendNumReq req) {
        return gaotuClient.getRecommendProgramNum(req);
    }

    @PostMapping("/program/query-by-limit-num")
    @ApiOperation("按分数查询院校专业录取方案")
    public ResponseDTO<java.util.List<QueryProgramByLimitNumRes>> queryProgramByLimitNum(
            @RequestBody QueryProgramLimitNumReq req,
            @ApiParam("租户ID，证据签发范围") @RequestParam(required = false) Long tenantId,
            @ApiParam("会话ID，证据签发范围") @RequestParam(required = false) Long chatSessionId,
            @ApiParam("线程ID，证据签发范围") @RequestParam(required = false) String threadId) {
        return gaotuClient.queryProgramByLimitNum(req, EvidenceScope.of(tenantId, chatSessionId, threadId));
    }

    @PostMapping("/score-line/query")
    @ApiOperation("查询院校专业历年录取分数线")
    public ResponseDTO<java.util.List<QuerySchoolMajorScoreLineRes>> querySchoolMajorScoreLine(
            @RequestBody QuerySchoolMajorScoreLineReq req,
            @ApiParam("租户ID，证据签发范围") @RequestParam(required = false) Long tenantId,
            @ApiParam("会话ID，证据签发范围") @RequestParam(required = false) Long chatSessionId,
            @ApiParam("线程ID，证据签发范围") @RequestParam(required = false) String threadId) {
        return gaotuClient.querySchoolMajorScoreLine(req, EvidenceScope.of(tenantId, chatSessionId, threadId));
    }
}
