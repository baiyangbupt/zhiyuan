package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.planning.*;
import com.ytell.zhiyuan.service.biz.PlanningStateService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/planning/{tenantId}")
@Slf4j
@Api(tags = "规划状态接口")
public class PlanningStateController {

    @Autowired
    private PlanningStateService planningStateService;

    @GetMapping("/session/state")
    @ApiOperation("获取完整规划状态")
    public BaseResponse<PlanningStateDTO> getState(@PathVariable("tenantId") Long tenantId,
                                                   @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getPlanningState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getPlanningState(chatSessionId));
    }

    @GetMapping("/session/workspace-state")
    @ApiOperation("获取工作台轻量规划状态")
    public BaseResponse<PlanningWorkspaceStateRes> getWorkspaceState(@PathVariable("tenantId") Long tenantId,
                                                                     @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getPlanningWorkspaceState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getPlanningWorkspaceState(chatSessionId));
    }

    @GetMapping("/session/summary")
    @ApiOperation("获取规划状态摘要")
    public BaseResponse<PlanningStateSummaryDTO> getSummary(@PathVariable("tenantId") Long tenantId,
                                                            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getPlanningStateSummary: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getPlanningStateSummary(chatSessionId));
    }

    @GetMapping("/session/profile")
    @ApiOperation("获取规划画像")
    public BaseResponse<ProfileStateDTO> getProfile(@PathVariable("tenantId") Long tenantId,
                                                    @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getPlanningProfile: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getProfileState(chatSessionId));
    }

    @GetMapping("/session/constraints")
    @ApiOperation("获取规划约束")
    public BaseResponse<ConstraintStateDTO> getConstraints(@PathVariable("tenantId") Long tenantId,
                                                           @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getPlanningConstraints: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getConstraintState(chatSessionId));
    }

    @PatchMapping("/session/constraints")
    @ApiOperation("更新规划约束和软偏好")
    public BaseResponse<PlanningStateVersionDTO> updateConstraintState(@PathVariable("tenantId") Long tenantId,
                                                                       @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                       @RequestBody UpdateConstraintStateReq req) {
        log.info("updateConstraintState: tenantId={}, chatSessionId={}, intentMode={}",
                tenantId, chatSessionId, req == null ? null : req.getIntentMode());
        return BaseResponse.success(planningStateService.updateConstraintState(chatSessionId, req));
    }

    @PatchMapping("/session/profile/explicit")
    @ApiOperation("更新显式画像")
    public BaseResponse<PlanningStateVersionDTO> updateExplicitProfile(@PathVariable("tenantId") Long tenantId,
                                                                       @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                       @RequestBody UpdateExplicitProfileReq req) {
        log.info("updateExplicitProfile: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.updateExplicitProfile(chatSessionId, req));
    }

    @PatchMapping("/session/profile/latent")
    @ApiOperation("更新潜在画像")
    public BaseResponse<PlanningStateVersionDTO> updateLatentProfile(@PathVariable("tenantId") Long tenantId,
                                                                     @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                     @RequestBody UpdateLatentProfileReq req) {
        log.info("updateLatentProfile: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.updateLatentProfile(chatSessionId, req));
    }

    @PatchMapping("/session/profile/physical")
    @ApiOperation("更新身体条件约束")
    public BaseResponse<PlanningStateVersionDTO> updatePhysicalConstraints(@PathVariable("tenantId") Long tenantId,
                                                                           @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                           @RequestBody UpdatePhysicalConstraintsReq req) {
        log.info("updatePhysicalConstraints: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.updatePhysicalConstraints(chatSessionId, req));
    }

    @PostMapping("/session/intent-change/stale")
    @ApiOperation("标记意向变更后的规划状态过期")
    public BaseResponse<PlanningStateVersionDTO> markIntentChangeStale(@PathVariable("tenantId") Long tenantId,
                                                                       @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                       @RequestBody(required = false) MarkPlanningIntentStaleReq req) {
        log.info("markIntentChangeStale: tenantId={}, chatSessionId={}, intentMode={}",
                tenantId, chatSessionId, req == null ? null : req.getIntentMode());
        return BaseResponse.success(planningStateService.markIntentChangeStale(chatSessionId, req));
    }

    @PostMapping("/session/constraints/derive")
    @ApiOperation("生成派生偏好")
    public BaseResponse<ConstraintDeriveRes> deriveConstraints(@PathVariable("tenantId") Long tenantId,
                                                               @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("derivePlanningConstraints: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.deriveConstraints(chatSessionId));
    }

    @PostMapping("/session/candidate-pool/generate")
    @ApiOperation("生成候选池")
    public BaseResponse<PlanningStateDTO> generateCandidatePool(@PathVariable("tenantId") Long tenantId,
                                                                @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                @RequestBody(required = false) CandidatePoolGenerateReq req) {
        log.info("generateCandidatePool: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateCandidatePool(tenantId, chatSessionId,
                req == null ? new CandidatePoolGenerateReq() : req));
    }

    @PostMapping("/session/candidate-pool/query")
    @ApiOperation("查询候选池")
    public BaseResponse<CandidatePoolQueryRes> queryCandidatePool(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                  @RequestBody CandidatePoolQueryReq req) {
        log.info("queryCandidatePool: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.queryCandidatePool(tenantId, chatSessionId, req));
    }

    @GetMapping("/session/candidate-pool/filter-options")
    @ApiOperation("获取候选池筛选项")
    public BaseResponse<CandidateFilterOptionsDTO> getCandidateFilterOptions(@PathVariable("tenantId") Long tenantId,
                                                                             @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getCandidateFilterOptions: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getCandidateFilterOptions(tenantId, chatSessionId));
    }

    @GetMapping("/session/candidate-view-state")
    @ApiOperation("获取候选视图状态")
    public BaseResponse<CandidateViewStateDTO> getCandidateViewState(@PathVariable("tenantId") Long tenantId,
                                                                     @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getCandidateViewState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getCandidateViewState(chatSessionId));
    }

    @PatchMapping("/session/candidate-view-state")
    @ApiOperation("更新候选视图状态")
    public BaseResponse<PlanningStateDTO> updateCandidateViewState(@PathVariable("tenantId") Long tenantId,
                                                                   @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                   @RequestBody(required = false) CandidateViewStateDTO req) {
        log.info("updateCandidateViewState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.updateCandidateViewState(chatSessionId,
                req == null ? new CandidateViewStateDTO() : req));
    }

    @GetMapping("/session/initial-recommendation")
    @ApiOperation("获取初始推荐结果")
    public BaseResponse<InitialRecommendationStateDTO> getInitialRecommendation(@PathVariable("tenantId") Long tenantId,
                                                                                @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getInitialRecommendation: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getInitialRecommendationState(chatSessionId));
    }

    @PostMapping("/session/initial-recommendation/generate")
    @ApiOperation("生成初始推荐结果")
    public BaseResponse<PlanningStateDTO> generateInitialRecommendation(@PathVariable("tenantId") Long tenantId,
                                                                        @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                        @RequestBody(required = false) InitialRecommendationGenerateReq req) {
        log.info("generateInitialRecommendation: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateInitialRecommendation(tenantId, chatSessionId,
                req == null ? new InitialRecommendationGenerateReq() : req));
    }

    @GetMapping("/session/plan-adjustment")
    @ApiOperation("获取方案调整分析结果")
    public BaseResponse<PlanAdjustmentStateDTO> getPlanAdjustment(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getPlanAdjustment: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getPlanAdjustmentState(chatSessionId));
    }

    @PostMapping("/session/plan-adjustment/analyze")
    @ApiOperation("分析方案调整建议")
    public BaseResponse<PlanAdjustmentStateDTO> analyzePlanAdjustment(@PathVariable("tenantId") Long tenantId,
                                                                      @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                      @RequestBody(required = false) PlanAdjustmentAnalyzeReq req) {
        log.info("analyzePlanAdjustment: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.analyzePlanAdjustment(tenantId, chatSessionId,
                req == null ? new PlanAdjustmentAnalyzeReq() : req));
    }

    @PostMapping("/session/plan-adjustment/apply")
    @ApiOperation("应用方案调整建议")
    public BaseResponse<PlanningStateDTO> applyPlanAdjustment(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody(required = false) PlanAdjustmentApplyReq req) {
        log.info("applyPlanAdjustment: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.applyPlanAdjustment(tenantId, chatSessionId,
                req == null ? new PlanAdjustmentApplyReq() : req));
    }

    // Deprecated route alias: /session/draft is retained only for 3.0.x and external compatibility.
    // New callers must use /session/working-plan.
    @GetMapping({"/session/working-plan", "/session/draft"})
    @ApiOperation("获取工作台方案")
    public BaseResponse<DraftPlanStateDTO> getWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                          @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getWorkingPlanState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getWorkingPlanState(chatSessionId));
    }

    @GetMapping("/session/ordered-plan")
    @ApiOperation("获取排序方案")
    public BaseResponse<OrderedPlanStateDTO> getOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getOrderedPlanState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getOrderedPlanState(chatSessionId));
    }

    @GetMapping("/session/review")
    @ApiOperation("获取审查结果")
    public BaseResponse<ReviewStateDTO> getReview(@PathVariable("tenantId") Long tenantId,
                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("getReviewState: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.getReviewState(chatSessionId));
    }

    @GetMapping("/review/rules")
    @ApiOperation("获取审查规则元数据")
    public BaseResponse<List<ReviewRuleMetadataDTO>> listReviewRules(@PathVariable("tenantId") Long tenantId) {
        log.info("listReviewRules: tenantId={}", tenantId);
        return BaseResponse.success(planningStateService.listReviewRuleMetadata());
    }

    // Deprecated route alias: /session/draft/select is retained only for 3.0.x and external compatibility.
    // New callers must use /session/working-plan/select.
    @PostMapping({"/session/working-plan/select", "/session/draft/select"})
    @ApiOperation("加入工作台方案")
    public BaseResponse<PlanningStateDTO> selectWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                            @RequestBody DraftSelectReq req) {
        log.info("selectWorkingPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.selectWorkingPlanItems(chatSessionId, req));
    }

    // Deprecated route alias: /session/draft/remove is retained only for 3.0.x and external compatibility.
    // New callers must use /session/working-plan/remove.
    @PostMapping({"/session/working-plan/remove", "/session/draft/remove"})
    @ApiOperation("移出工作台方案")
    public BaseResponse<PlanningStateDTO> removeWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                            @RequestBody DraftRemoveReq req) {
        log.info("removeWorkingPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.removeWorkingPlanItems(chatSessionId, req));
    }

    // Deprecated route alias: /session/draft/lock is retained only for 3.0.x and external compatibility.
    // New callers must use /session/working-plan/lock.
    @PostMapping({"/session/working-plan/lock", "/session/draft/lock"})
    @ApiOperation("锁定工作台方案项")
    public BaseResponse<PlanningStateDTO> lockWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                          @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                          @RequestBody DraftLockReq req) {
        log.info("lockWorkingPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.lockWorkingPlanItems(chatSessionId, req));
    }

    // Deprecated route alias: /session/draft/ban is retained only for 3.0.x and external compatibility.
    // New callers must use /session/working-plan/ban.
    @PostMapping({"/session/working-plan/ban", "/session/draft/ban"})
    @ApiOperation("禁用候选项")
    public BaseResponse<PlanningStateDTO> banWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                         @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                         @RequestBody DraftBanReq req) {
        log.info("banWorkingPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.banWorkingPlanItems(chatSessionId, req));
    }

    @PostMapping("/session/ordered-plan/generate")
    @ApiOperation("生成排序方案")
    public BaseResponse<PlanningStateDTO> generateOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody(required = false) OrderedPlanGenerateReq req) {
        log.info("generateOrderedPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateOrderedPlan(tenantId, chatSessionId,
                req == null ? new OrderedPlanGenerateReq() : req));
    }

    @PostMapping("/session/initial-plan/generate")
    @ApiOperation("生成初始默认方案")
    public BaseResponse<PlanningStateDTO> generateInitialPlan(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody(required = false) InitialPlanGenerateReq req) {
        log.info("generateInitialPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateInitialPlan(tenantId, chatSessionId,
                req == null ? new InitialPlanGenerateReq() : req));
    }

    // Deprecated route alias: /session/draft/reorder is retained only for 3.0.x and external compatibility.
    // New callers must use /session/working-plan/reorder.
    @PostMapping({"/session/working-plan/reorder", "/session/draft/reorder"})
    @ApiOperation("对当前工作台方案生成建议排序")
    public BaseResponse<PlanningStateDTO> reorderWorkingPlan(@PathVariable("tenantId") Long tenantId,
                                                             @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                             @RequestBody(required = false) DraftPlanReorderReq req) {
        log.info("reorderWorkingPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.reorderWorkingPlan(tenantId, chatSessionId,
                req == null ? new DraftPlanReorderReq() : req));
    }

    @PostMapping("/session/ordered-plan/move")
    @ApiOperation("移动排序项")
    public BaseResponse<OrderedPlanActionRes> moveOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody OrderedMoveReq req) {
        log.info("moveOrderedPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.moveOrderedItem(chatSessionId, req)));
    }

    @PostMapping("/session/ordered-plan/unit/move")
    @ApiOperation("移动排序专业组")
    public BaseResponse<OrderedPlanActionRes> moveOrderedPlanUnit(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                  @RequestBody OrderedUnitMoveReq req) {
        log.info("moveOrderedPlanUnit: tenantId={}, chatSessionId={}, unitId={}", tenantId, chatSessionId,
                req == null ? null : req.getUnitId());
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.moveOrderedUnit(chatSessionId, req)));
    }

    @PostMapping("/session/ordered-plan/unit/remove")
    @ApiOperation("删除排序专业组")
    public BaseResponse<OrderedPlanActionRes> removeOrderedPlanUnit(@PathVariable("tenantId") Long tenantId,
                                                                    @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                    @RequestBody OrderedUnitRemoveReq req) {
        log.info("removeOrderedPlanUnit: tenantId={}, chatSessionId={}, unitIds={}", tenantId, chatSessionId,
                req == null ? null : req.getUnitIds());
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.removeOrderedUnits(chatSessionId, req)));
    }

    @PostMapping("/session/ordered-plan/sort")
    @ApiOperation("按指定维度重排当前方案")
    public BaseResponse<OrderedPlanActionRes> sortOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody OrderedPlanSortReq req) {
        log.info("sortOrderedPlan: tenantId={}, chatSessionId={}, sortField={}", tenantId, chatSessionId,
                req == null ? null : req.getSortField());
        return BaseResponse.success(planningStateService.buildOrderedPlanActionRes(
                planningStateService.sortOrderedPlan(chatSessionId, req)));
    }

    @PostMapping("/session/ordered-plan/export")
    @ApiOperation("导出当前排序方案")
    public ResponseEntity<ByteArrayResource> exportOrderedPlan(@PathVariable("tenantId") Long tenantId,
                                                               @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("exportOrderedPlan: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
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
            log.error("exportOrderedPlan failed", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }

    @PostMapping("/session/review/run")
    @ApiOperation("执行方案审查")
    public BaseResponse<ReviewStateDTO> runReview(@PathVariable("tenantId") Long tenantId,
                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("runReview: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.runReview(tenantId, chatSessionId));
    }

    @PostMapping("/session/review-workflow/run")
    @ApiOperation("执行方案审查并生成修复建议")
    public BaseResponse<ReviewWorkflowRunRes> runReviewWorkflow(@PathVariable("tenantId") Long tenantId,
                                                                @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("runReviewWorkflow: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.runReviewWorkflow(tenantId, chatSessionId));
    }

    @PostMapping("/session/compensation/preview")
    @ApiOperation("预览补偿建议")
    public BaseResponse<CompensationPreviewDTO> previewCompensation(@PathVariable("tenantId") Long tenantId,
                                                                    @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("previewCompensation: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.previewCompensation(tenantId, chatSessionId));
    }

    @PostMapping("/session/fix-proposals/generate")
    @ApiOperation("生成风险修复建议")
    public BaseResponse<FixProposalStateDTO> generateFixProposals(@PathVariable("tenantId") Long tenantId,
                                                                  @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId) {
        log.info("generateFixProposals: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.generateFixProposals(tenantId, chatSessionId));
    }

    @PostMapping("/session/fix-proposals/user-goal/generate")
    @ApiOperation("按用户复合目标生成只读方案调整预览")
    public BaseResponse<FixProposalStateDTO> generateUserGoalFixProposals(@PathVariable("tenantId") Long tenantId,
                                                                          @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                                          @RequestBody(required = false) UserGoalFixProposalReq req) {
        log.info("generateUserGoalFixProposals: tenantId={}, chatSessionId={}, goalType={}",
                tenantId, chatSessionId, req == null ? null : req.getGoalType());
        return BaseResponse.success(planningStateService.generateUserGoalFixProposals(chatSessionId, req));
    }

    @PostMapping("/session/fix-proposals/apply")
    @ApiOperation("应用风险修复建议")
    public BaseResponse<FixProposalApplyRes> applyFixProposal(@PathVariable("tenantId") Long tenantId,
                                                              @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                              @RequestBody(required = false) FixProposalApplyReq req) {
        log.info("applyFixProposal: tenantId={}, chatSessionId={}, proposalId={}",
                tenantId, chatSessionId, req == null ? null : req.getProposalId());
        return BaseResponse.success(planningStateService.applyFixProposal(tenantId, chatSessionId, req));
    }

    @PostMapping("/session/compensation/apply")
    @ApiOperation("兼容应用低风险补偿建议，结构修复请使用 fix-proposals/apply")
    public BaseResponse<PlanningStateDTO> applyCompensation(@PathVariable("tenantId") Long tenantId,
                                                            @ApiParam("会话ID") @RequestParam("chatSessionId") Long chatSessionId,
                                                            @RequestBody(required = false) CompensationApplyReq req) {
        log.info("applyCompensation: tenantId={}, chatSessionId={}", tenantId, chatSessionId);
        return BaseResponse.success(planningStateService.applyCompensation(tenantId, chatSessionId,
                req == null ? new CompensationApplyReq() : req));
    }
}
