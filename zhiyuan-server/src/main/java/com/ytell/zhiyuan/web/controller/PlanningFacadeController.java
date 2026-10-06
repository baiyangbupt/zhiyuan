package com.ytell.zhiyuan.web.controller;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateFilterOptionsDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryRes;
import com.ytell.zhiyuan.model.dto.planning.CandidatePreviewReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePreviewRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateViewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessCheckReq;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessCheckRes;
import com.ytell.zhiyuan.model.dto.planning.DraftRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.DraftSelectReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.InitialPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedMoveReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanActionRes;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitMoveReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.dto.planning.ReviewWorkflowRunRes;
import com.ytell.zhiyuan.service.biz.CandidatePreviewService;
import com.ytell.zhiyuan.service.biz.ConversationAccessService;
import com.ytell.zhiyuan.service.biz.EvidenceLedgerService;
import com.ytell.zhiyuan.service.biz.PlanningStateService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Date;
import java.util.List;

/**
 * 工作台公开 facade。
 *
 * <p>存在的理由：工作台此前直连 {@code /gaotu-assistant-bot/inner/planning/...}——
 * inner 面无鉴权，封堵后浏览器调用会 404。这里为浏览器提供**带登录与 session
 * ownership 校验**的同构路径，使前端可以纯路径替换，不改变任何返回结构与业务码
 * （含 CAS 冲突码 40903–40906 与导出的 Content-Disposition）。</p>
 *
 * <p>两条硬规则：</p>
 * <ul>
 *   <li>每个方法**先** {@link ConversationAccessService#requireOwnedSession} 再委托
 *       现有 {@code PlanningStateService}，不信任请求里的任何身份字段；</li>
 *   <li>禁止通配路径透传 inner——inner 面继续只给 agent 用，且不受登录拦截。</li>
 * </ul>
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/chat/{tenantId}/planning/session")
@Slf4j
@Api(tags = "工作台规划接口（公开 facade）")
public class PlanningFacadeController {

    @Autowired
    private ConversationAccessService conversationAccessService;
    @Autowired
    private PlanningStateService planningStateService;
    @Autowired
    private EvidenceLedgerService evidenceLedgerService;
    @Autowired
    private CandidatePreviewService candidatePreviewService;

    /**
     * 会话归属校验，facade 的唯一入口。
     *
     * <p>principal 取登录态线程缓存（{@code LoginInterceptor} 在放行前写入）。
     * 缺失时回 401 而不是 NPE：这是"没登录"而不是"没权限"。</p>
     */
    private void requireOwnedSession(Long tenantId, Long chatSessionId) {
        UserBaseData principal = UserInfoThreadLocalUtil.get();
        Long principalUserId = principal == null ? null : principal.getUserId();
        if (principalUserId == null) {
            throw new ConversationAccessException(401, "unauthenticated");
        }
        conversationAccessService.requireOwnedSession(tenantId, chatSessionId, principalUserId);
    }

    @GetMapping("/workspace-state")
    @ApiOperation("获取工作台轻量规划状态")
    public BaseResponse<PlanningWorkspaceStateRes> getWorkspaceState(@PathVariable("tenantId") Long tenantId,
                                                                     @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade getPlanningWorkspaceState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getPlanningWorkspaceState(tenantId, chatSessionId));
    }

    @PostMapping("/candidate-pool/query")
    @ApiOperation("查询候选池")
    public BaseResponse<CandidatePoolQueryRes> queryCandidatePool(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                  @RequestBody CandidatePoolQueryReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade queryCandidatePool: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.queryCandidatePool(tenantId, chatSessionId, req));
    }

    @PostMapping("/candidate-preview")
    @ApiOperation("候选预览（只读，不落规划状态）")
    public BaseResponse<CandidatePreviewRes> previewCandidates(@PathVariable("tenantId") Long tenantId,
                                                               @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                               @RequestBody(required = false) CandidatePreviewReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade previewCandidates: tenantId={}, chatSessionId={}, page={}", tenantId, chatSessionId,
                req == null ? null : req.getPage());
        return BaseResponse.success(candidatePreviewService.preview(tenantId, chatSessionId, req));
    }

    @GetMapping("/candidate-pool/filter-options")
    @ApiOperation("获取候选池筛选项")
    public BaseResponse<CandidateFilterOptionsDTO> getCandidateFilterOptions(@PathVariable("tenantId") Long tenantId,
                                                                             @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade getCandidateFilterOptions: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getCandidateFilterOptions(tenantId, chatSessionId));
    }

    @PostMapping("/ordered-plan/export")
    @ApiOperation("导出当前排序方案")
    public ResponseEntity<ByteArrayResource> exportOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                               @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade exportOrderedPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        try {
            PlanningStateService.ExcelExportResult exportResult = planningStateService.exportOrderedPlan(tenantId, chatSessionId);
            ByteArrayResource resource = new ByteArrayResource(exportResult.getExcelData());
            HttpHeaders headers = new HttpHeaders();
            String fileName = exportResult.getFileName();
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
            log.error("facade exportOrderedPlan failed", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }

    @PostMapping("/data-freshness/check")
    @ApiOperation("检查并标记招生计划数据更新")
    public BaseResponse<DataFreshnessCheckRes> checkDataFreshness(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                  @RequestBody(required = false) DataFreshnessCheckReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade checkDataFreshness: tenantId={}, chatSessionId={}, changeLevel={}",
                tenantId, chatSessionId, req == null ? null : req.getChangeLevel());
        return BaseResponse.success(planningStateService.checkDataFreshness(tenantId, chatSessionId,
                req == null ? new DataFreshnessCheckReq() : req));
    }

    @PostMapping("/review-workflow/run")
    @ApiOperation("执行方案审查并生成修复建议")
    public BaseResponse<ReviewWorkflowRunRes> runReviewWorkflow(@PathVariable("tenantId") Long tenantId,
                                                                @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade runReviewWorkflow: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.runReviewWorkflow(tenantId, chatSessionId));
    }

    @PostMapping("/fix-proposals/generate")
    @ApiOperation("生成风险修复建议")
    public BaseResponse<FixProposalStateDTO> generateFixProposals(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade generateFixProposals: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateFixProposals(tenantId, chatSessionId));
    }

    /**
     * 注意：{@code sourceVersionGuard} 的 CAS 语义与 40904 冲突码全部由既有服务判定，
     * 这里原样透传请求体（含 null），不在这里做任何版本判断。
     */
    @PostMapping("/fix-proposals/apply")
    @ApiOperation("应用风险修复建议")
    public BaseResponse<FixProposalApplyRes> applyFixProposal(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody(required = false) FixProposalApplyReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade applyFixProposal: tenantId={}, chatSessionId={}, proposalId={}",
                tenantId, chatSessionId, req == null ? null : req.getProposalId());
        return BaseResponse.success(planningStateService.applyFixProposal(tenantId, chatSessionId, req));
    }

    @PostMapping("/candidate-pool/generate")
    @ApiOperation("生成候选池")
    public BaseResponse<PlanningStateDTO> generateCandidatePool(@PathVariable("tenantId") Long tenantId,
                                                                @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                @RequestBody(required = false) CandidatePoolGenerateReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade generateCandidatePool: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateCandidatePool(tenantId, chatSessionId,
                req == null ? new CandidatePoolGenerateReq() : req));
    }

    @PostMapping("/initial-plan/generate")
    @ApiOperation("生成初始默认方案")
    public BaseResponse<PlanningStateDTO> generateInitialPlan(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody(required = false) InitialPlanGenerateReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade generateInitialPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateInitialPlan(tenantId, chatSessionId,
                req == null ? new InitialPlanGenerateReq() : req));
    }

    @PatchMapping("/candidate-view-state")
    @ApiOperation("更新候选视图状态")
    public BaseResponse<PlanningStateDTO> updateCandidateViewState(@PathVariable("tenantId") Long tenantId,
                                                                   @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                   @RequestBody(required = false) CandidateViewStateDTO req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade updateCandidateViewState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.updateCandidateViewState(chatSessionId,
                req == null ? new CandidateViewStateDTO() : req));
    }

    @PostMapping("/working-plan/select")
    @ApiOperation("加入工作台方案")
    public BaseResponse<PlanningStateDTO> selectWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                            @RequestBody DraftSelectReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade selectWorkingPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.selectWorkingPlanItems(chatSessionId, req));
    }

    @PostMapping("/working-plan/remove")
    @ApiOperation("移出工作台方案")
    public BaseResponse<PlanningStateDTO> removeWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                            @RequestBody DraftRemoveReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade removeWorkingPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.removeWorkingPlanItems(chatSessionId, req));
    }

    @PostMapping("/ordered-plan/move")
    @ApiOperation("移动排序项")
    public BaseResponse<OrderedPlanActionRes> moveOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody OrderedMoveReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade moveOrderedPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.moveOrderedItem(chatSessionId, req)));
    }

    @PostMapping("/ordered-plan/unit/move")
    @ApiOperation("移动排序专业组")
    public BaseResponse<OrderedPlanActionRes> moveOrderedPlanUnit(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                  @RequestBody OrderedUnitMoveReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade moveOrderedPlanUnit: tenantId={}, chatSessionId={}, unitId={}", tenantId, chatSessionId,
                req == null ? null : req.getUnitId());
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.moveOrderedUnit(chatSessionId, req)));
    }

    @PostMapping("/ordered-plan/unit/remove")
    @ApiOperation("删除排序专业组")
    public BaseResponse<OrderedPlanActionRes> removeOrderedPlanUnit(@PathVariable("tenantId") Long tenantId,
                                                                    @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                    @RequestBody OrderedUnitRemoveReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade removeOrderedPlanUnit: tenantId={}, chatSessionId={}, unitIds={}", tenantId, chatSessionId,
                req == null ? null : req.getUnitIds());
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.removeOrderedUnits(chatSessionId, req)));
    }

    @PostMapping("/ordered-plan/sort")
    @ApiOperation("按指定维度重排当前方案")
    public BaseResponse<OrderedPlanActionRes> sortOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody OrderedPlanSortReq req) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade sortOrderedPlan: tenantId={}, chatSessionId={}, sortField={}", tenantId, chatSessionId,
                req == null ? null : req.getSortField());
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.sortOrderedPlan(chatSessionId, req)));
    }

    /**
     * 证据详情（inner 侧不存在，前端一直 404）。
     *
     * <p>只能**先按会话列证据、再按 evidenceId 命中**：按 evidenceId 裸查等于给任何
     * 登录用户一个跨会话的证据探测器。未命中（不存在 / 已过期 / stale / 属于别的会话）
     * 统一 404 {@code evidence_not_found}，不区分原因——这与
     * {@link EvidenceLedgerService#listSessionEvidence} 的"只回 valid"口径一致。</p>
     */
    @GetMapping("/evidence")
    @ApiOperation("查询会话证据")
    public ResponseEntity<BaseResponse<ConversationEvidenceDTO>> getEvidence(
            @PathVariable("tenantId") Long tenantId,
            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
            @ApiParam("证据ID") @RequestParam("evidenceId") String evidenceId) {
        requireOwnedSession(tenantId, chatSessionId);
        log.info("facade getEvidence: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        List<ConversationEvidenceDTO> evidenceList =
                evidenceLedgerService.listSessionEvidence(tenantId, chatSessionId, new Date());
        if (evidenceId != null) {
            for (ConversationEvidenceDTO evidence : evidenceList) {
                if (evidenceId.equals(evidence.getEvidenceId())) {
                    return ResponseEntity.ok(BaseResponse.success(evidence));
                }
            }
        }
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(BaseResponse.error(HttpStatus.NOT_FOUND.value(), "evidence_not_found"));
    }
}
