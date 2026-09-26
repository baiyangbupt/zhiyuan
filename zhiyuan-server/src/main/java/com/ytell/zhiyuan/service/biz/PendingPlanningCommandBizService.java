package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.DraftSelectReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

@Service
public class PendingPlanningCommandBizService {

    public static final int COMMAND_CONFLICT_CODE = 40903;
    public static final int PLAN_VERSION_CONFLICT_CODE = 40904;
    public static final int POSTCONDITION_FAILED_CODE = 40905;
    /** 约束变更会把方案排空：拒绝执行并回滚，不留一个被清空的方案。 */
    public static final int CONSTRAINT_EMPTIES_PLAN_CODE = 40906;
    public static final String APPLY_CONSTRAINT_AND_REGENERATE = "apply_constraint_and_regenerate";
    public static final String ADD_UNITS = "add_units";
    public static final String REPLACE_UNITS = "replace_units";
    public static final String APPLY_PLAN_CHANGE_PROPOSAL = "apply_plan_change_proposal";

    @Autowired
    private PlanningPendingCommandSharedService commandSharedService;
    @Autowired
    private PendingConfirmationSharedService pendingSharedService;
    @Autowired
    private ChatSessionExtraDataSharedService extraDataSharedService;
    @Autowired
    private PlanningStateService planningStateService;
    @Autowired
    private ChatSessionBizService chatSessionBizService;
    @Autowired
    private UnifiedPlanPostconditionValidator postconditionValidator;

    @Transactional(rollbackFor = Exception.class)
    public PendingPlanningCommandRes execute(Long tenantId, Long chatSessionId,
                                             PendingPlanningCommandReq req) {
        validate(tenantId, chatSessionId, req);
        PlanningPendingCommandEntity existing = commandSharedService.getByOperationId(req.getOperationId());
        if (existing != null) {
            validatePendingOwner(tenantId, chatSessionId, req);
            return replay(existing, tenantId, chatSessionId, req);
        }

        validatePendingOwner(tenantId, chatSessionId, req);
        extraDataSharedService.lockBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        existing = commandSharedService.getByOperationId(req.getOperationId());
        if (existing != null) {
            return replay(existing, tenantId, chatSessionId, req);
        }
        PlanningStateDTO before = planningStateService.getPlanningState(chatSessionId);
        int currentVersion = before.getVersion() == null ? 0 : before.getVersion();
        if (currentVersion != req.getExpectedPlanVersion()) {
            throw new BusinessException(PLAN_VERSION_CONFLICT_CODE,
                    "planning version conflict: current=" + currentVersion
                            + " expected=" + req.getExpectedPlanVersion());
        }

        PlanningPendingCommandEntity command = buildCommand(tenantId, chatSessionId, req);
        try {
            commandSharedService.save(command);
        } catch (DuplicateKeyException ex) {
            PlanningPendingCommandEntity concurrent = commandSharedService.getByOperationId(req.getOperationId());
            if (concurrent != null && "succeeded".equals(concurrent.getStatus())) {
                return replay(concurrent, tenantId, chatSessionId, req);
            }
            throw new BusinessException(COMMAND_CONFLICT_CODE, "planning command is already running");
        }

        PendingPlanningCommandRes result = executeCommand(tenantId, chatSessionId, req, currentVersion);
        command.setStatus("succeeded");
        command.setResultJson(JSONObject.toJSONString(compactResultForReplay(result)));
        commandSharedService.updateById(command);
        return result;
    }

    /**
     * 约束把方案排空时**拒绝执行**，交给事务整体回滚。
     *
     * <p>不追求"部分成功"：宁可整条命令失败、状态保持原样，也不留一个被清空的方案。
     * 用户能看到的差别是"这次没改成"而不是"我的方案没了"。
     */
    private PlanningStateDTO assertConstraintDidNotEmptyPlan(PlanningStateDTO before, PlanningStateDTO after) {
        int beforeCount = workingPlanItemCount(before);
        int afterCount = workingPlanItemCount(after);
        if (beforeCount > 0 && afterCount == 0) {
            throw new BusinessException(CONSTRAINT_EMPTIES_PLAN_CODE,
                    "当前约束下方案里没有可保留的条目，未做任何修改（原方案 " + beforeCount + " 条）");
        }
        return after;
    }

    private static int workingPlanItemCount(PlanningStateDTO state) {
        if (state == null || state.getDraftPlanState() == null
                || state.getDraftPlanState().getItems() == null) {
            return 0;
        }
        return state.getDraftPlanState().getItems().size();
    }

    private PendingPlanningCommandRes executeCommand(Long tenantId, Long chatSessionId,
                                                     PendingPlanningCommandReq req,
                                                     int sourceVersion) {
        List<String> steps = new ArrayList<String>();
        PlanningStateDTO state;
        FixProposalApplyRes proposalApplyRes = null;
        if (APPLY_CONSTRAINT_AND_REGENERATE.equals(req.getCommandType())) {
            if (req.getConstraintUpdate() != null) {
                planningStateService.updateConstraintState(chatSessionId, req.getConstraintUpdate());
                steps.add("constraint_updated");
            }
            if (req.getMaxTuitionPerYear() != null) {
                chatSessionBizService.updateTuitionRange(
                        tenantId, chatSessionId, req.getMinTuitionPerYear(), req.getMaxTuitionPerYear());
                steps.add("tuition_updated");
            }
            if (Boolean.TRUE.equals(req.getRegenerateOrderedPlan())) {
                // 两段，顺序不能反 ✓：
                //   ① 同步——重生成会**按新约束同步工作方案**（同步＝"按合格候选重建草案"）。
                //      一条把候选全滤掉的约束会把工作方案清成 0 行，而那是**不可逆**的：
                //      有序方案由工作方案生成，此后任何重生成都从空方案出发
                //      （2026-09-25 真栈实测：修好匹配器后仍为 0 单元）。所以先记下规模，被排空就回滚。
                //   ② 补足——把方案按档位目标数拉回规模 ✓。**必须在同步之后**：档位计数若把
                //      "即将被删掉的条目"算进去，补足量就错了（这是接线 `addAutoSelectedByTier`
                //      时最容易踩的一处 ✗）。补进来的都是合格候选 ✓，第二段重生成不会再删它们 ✓。
                PlanningStateDTO beforeRegenerate = planningStateService.getPlanningState(chatSessionId);
                state = assertConstraintDidNotEmptyPlan(beforeRegenerate,
                        planningStateService.generateOrderedPlan(tenantId, chatSessionId, forceOrderedRegenerate()));
                steps.add("ordered_plan_regenerated");
                planningStateService.refillWorkingPlanByTierTargets(tenantId, chatSessionId);
                steps.add("working_plan_refilled");
                state = assertConstraintDidNotEmptyPlan(
                        planningStateService.getPlanningState(chatSessionId),
                        planningStateService.generateOrderedPlan(tenantId, chatSessionId, forceOrderedRegenerate()));
            } else {
                state = planningStateService.getPlanningState(chatSessionId);
            }
        } else if (ADD_UNITS.equals(req.getCommandType()) || REPLACE_UNITS.equals(req.getCommandType())) {
            if (REPLACE_UNITS.equals(req.getCommandType())) {
                OrderedUnitRemoveReq removeReq = new OrderedUnitRemoveReq();
                removeReq.setUnitIds(req.getUnitIds());
                planningStateService.removeOrderedUnits(chatSessionId, removeReq);
                steps.add("ordered_units_removed");
            }

            DraftSelectReq selectReq = new DraftSelectReq();
            selectReq.setVolunteerIds(req.getVolunteerIds());
            selectReq.setSource("pending_command");
            planningStateService.selectWorkingPlanItems(chatSessionId, selectReq);
            steps.add("working_plan_items_selected");

            state = planningStateService.generateOrderedPlan(tenantId, chatSessionId, forceOrderedRegenerate());
            steps.add("ordered_plan_regenerated");
        } else if (APPLY_PLAN_CHANGE_PROPOSAL.equals(req.getCommandType())) {
            proposalApplyRes = planningStateService.applyFixProposal(
                    tenantId, chatSessionId, req.getProposalApply());
            state = proposalApplyRes.getState();
            steps.add("proposal_applied");
            steps.add("ordered_plan_regenerated");
            steps.add("review_rerun");
        } else {
            throw new BusinessException(40001, "unsupported commandType: " + req.getCommandType());
        }

        PendingPlanningCommandRes result = new PendingPlanningCommandRes();
        result.setOperationId(req.getOperationId());
        result.setPendingId(req.getPendingId());
        result.setCommandType(req.getCommandType());
        result.setSourcePlanVersion(sourceVersion);
        result.setResultPlanVersion(state.getVersion() == null ? 0 : state.getVersion());
        result.setCompletedSteps(steps);
        if (APPLY_PLAN_CHANGE_PROPOSAL.equals(req.getCommandType())) {
            result.setPostconditionReport(postconditionValidator.validate(req, state, proposalApplyRes));
            steps.add("postcondition_verified");
        }
        if (APPLY_CONSTRAINT_AND_REGENERATE.equals(req.getCommandType())) {
            // 约束路以前没有满足度信号（DTO 里连 status 都没有 → 网关只能判 failed ✗）。
            // 补上，并且不满足就抛 40905 回滚：约束没生效就别改用户的方案 ✓。
            result.setPostconditionReport(
                    postconditionValidator.validateConstraintApply(req.getCommandType(), state));
            steps.add("postcondition_verified");
        }
        result.setPlanningState(state);
        result.setReplayed(false);
        return result;
    }

    private OrderedPlanGenerateReq forceOrderedRegenerate() {
        OrderedPlanGenerateReq req = new OrderedPlanGenerateReq();
        req.setForceRegenerate(true);
        req.setRegroupByTier(true);
        return req;
    }

    private void validatePendingOwner(Long tenantId, Long chatSessionId, PendingPlanningCommandReq req) {
        PendingConfirmationEntity pending = pendingSharedService.lockCurrent(tenantId, chatSessionId);
        if (pending == null
                || !req.getPendingId().equals(pending.getPendingId())
                || !"applying".equals(pending.getStatus())
                || !req.getClaimToken().equals(pending.getClaimToken())
                || pending.getClaimExpiresAt() == null
                || pending.getClaimExpiresAt().getTime() <= System.currentTimeMillis()) {
            throw new BusinessException(PendingConfirmationBizService.PENDING_MISMATCH_CODE,
                    "pending command owner mismatch");
        }
    }

    private PendingPlanningCommandRes replay(PlanningPendingCommandEntity existing,
                                             Long tenantId, Long chatSessionId,
                                             PendingPlanningCommandReq req) {
        if (!tenantId.equals(existing.getTenantId())
                || !chatSessionId.equals(existing.getChatSessionId())
                || !req.getPendingId().equals(existing.getPendingId())
                || !req.getCommandType().equals(existing.getCommandType())
                || !req.getExpectedPlanVersion().equals(existing.getExpectedPlanVersion())
                || !requestDigest(req).equals(existing.getRequestDigest())) {
            throw new BusinessException(COMMAND_CONFLICT_CODE, "operationId was used by another command");
        }
        if (!"succeeded".equals(existing.getStatus()) || Strings.isNullOrEmpty(existing.getResultJson())) {
            throw new BusinessException(COMMAND_CONFLICT_CODE, "planning command is already running");
        }
        PendingPlanningCommandRes result = JSONObject.parseObject(
                existing.getResultJson(), PendingPlanningCommandRes.class);
        result.setReplayed(true);
        return result;
    }

    private PlanningPendingCommandEntity buildCommand(Long tenantId, Long chatSessionId,
                                                      PendingPlanningCommandReq req) {
        PlanningPendingCommandEntity entity = new PlanningPendingCommandEntity();
        entity.setTenantId(tenantId);
        entity.setChatSessionId(chatSessionId);
        entity.setPendingId(req.getPendingId());
        entity.setOperationId(req.getOperationId());
        entity.setCommandType(req.getCommandType());
        entity.setExpectedPlanVersion(req.getExpectedPlanVersion());
        entity.setRequestDigest(requestDigest(req));
        entity.setStatus("running");
        return entity;
    }

    private PendingPlanningCommandRes compactResultForReplay(PendingPlanningCommandRes source) {
        PendingPlanningCommandRes compact = new PendingPlanningCommandRes();
        compact.setOperationId(source.getOperationId());
        compact.setPendingId(source.getPendingId());
        compact.setCommandType(source.getCommandType());
        compact.setSourcePlanVersion(source.getSourcePlanVersion());
        compact.setResultPlanVersion(source.getResultPlanVersion());
        compact.setCompletedSteps(new ArrayList<String>(source.getCompletedSteps()));
        compact.setPostconditionReport(source.getPostconditionReport());
        compact.setReplayed(false);
        PlanningStateDTO state = source.getPlanningState();
        if (state != null) {
            PlanningStateDTO replayState = new PlanningStateDTO();
            replayState.setSessionId(state.getSessionId());
            replayState.setVersion(state.getVersion());
            replayState.setPhase(state.getPhase());
            replayState.setOrderedPlanState(state.getOrderedPlanState());
            replayState.setStaleFlags(null);
            replayState.setProfileState(null);
            replayState.setConstraintState(null);
            replayState.setDataFreshnessState(null);
            replayState.setCandidatePoolState(null);
            replayState.setCandidateViewState(null);
            replayState.setInitialRecommendationState(null);
            replayState.setRecommendationOverlayState(null);
            replayState.setPlanGenerationState(null);
            replayState.setWorkingPlanState(null);
            replayState.setPlanAdjustmentState(null);
            replayState.setReviewState(null);
            replayState.setOperationLogs(null);
            compact.setPlanningState(replayState);
        }
        return compact;
    }

    private String requestDigest(PendingPlanningCommandReq req) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            PendingPlanningCommandReq stable = new PendingPlanningCommandReq();
            stable.setOperationId(req.getOperationId());
            stable.setPendingId(req.getPendingId());
            stable.setExpectedPlanVersion(req.getExpectedPlanVersion());
            stable.setCommandType(req.getCommandType());
            stable.setConstraintUpdate(req.getConstraintUpdate());
            stable.setMinTuitionPerYear(req.getMinTuitionPerYear());
            stable.setMaxTuitionPerYear(req.getMaxTuitionPerYear());
            stable.setRegenerateOrderedPlan(req.getRegenerateOrderedPlan());
            stable.setUnitIds(req.getUnitIds());
            stable.setVolunteerIds(req.getVolunteerIds());
            stable.setProposalApply(req.getProposalApply());
            byte[] value = digest.digest(JSONObject.toJSONString(stable).getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(value.length * 2);
            for (byte item : value) {
                result.append(String.format("%02x", item & 0xff));
            }
            return result.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    private void validate(Long tenantId, Long chatSessionId, PendingPlanningCommandReq req) {
        if (tenantId == null || tenantId <= 0L || chatSessionId == null || chatSessionId <= 0L || req == null) {
            throw new BusinessException(40001, "tenantId, chatSessionId and request are required");
        }
        requireText(req.getOperationId(), "operationId");
        requireText(req.getPendingId(), "pendingId");
        requireText(req.getClaimToken(), "claimToken");
        requireText(req.getCommandType(), "commandType");
        if (req.getOperationId().length() > 64) {
            throw new BusinessException(40001, "operationId is too long");
        }
        if (req.getExpectedPlanVersion() == null || req.getExpectedPlanVersion() < 0) {
            throw new BusinessException(40001, "expectedPlanVersion must be >= 0");
        }
        if (!APPLY_CONSTRAINT_AND_REGENERATE.equals(req.getCommandType())
                && !ADD_UNITS.equals(req.getCommandType())
                && !REPLACE_UNITS.equals(req.getCommandType())
                && !APPLY_PLAN_CHANGE_PROPOSAL.equals(req.getCommandType())) {
            throw new BusinessException(40001, "unsupported commandType: " + req.getCommandType());
        }
        if (ADD_UNITS.equals(req.getCommandType())
                && (req.getVolunteerIds() == null || req.getVolunteerIds().isEmpty())) {
            throw new BusinessException(40001, "add_units requires volunteerIds");
        }
        if (REPLACE_UNITS.equals(req.getCommandType())
                && (req.getUnitIds() == null || req.getUnitIds().isEmpty()
                || req.getVolunteerIds() == null || req.getVolunteerIds().isEmpty())) {
            throw new BusinessException(40001, "replace_units requires unitIds and volunteerIds");
        }
        if (APPLY_CONSTRAINT_AND_REGENERATE.equals(req.getCommandType())
                && req.getConstraintUpdate() == null && req.getMaxTuitionPerYear() == null) {
            throw new BusinessException(40001,
                    "apply_constraint_and_regenerate requires constraintUpdate or tuition range");
        }
        if (req.getMaxTuitionPerYear() != null
                && (req.getMaxTuitionPerYear() <= 0
                || (req.getMinTuitionPerYear() != null
                && (req.getMinTuitionPerYear() < 0
                || req.getMinTuitionPerYear() > req.getMaxTuitionPerYear())))) {
            throw new BusinessException(40001, "invalid tuition range");
        }
        if (APPLY_PLAN_CHANGE_PROPOSAL.equals(req.getCommandType())) {
            validatePlanChangeProposal(req);
        }
    }

    private void validatePlanChangeProposal(PendingPlanningCommandReq req) {
        FixProposalApplyReq applyReq = req.getProposalApply();
        if (applyReq == null || Strings.isNullOrEmpty(applyReq.getProposalId())) {
            throw new BusinessException(40001,
                    "apply_plan_change_proposal requires proposalApply and proposalId");
        }
        if (!req.getExpectedPlanVersion().equals(applyReq.getSourceVersionGuard())) {
            throw new BusinessException(40001, "plan change source version must match expectedPlanVersion");
        }
        if (!Boolean.TRUE.equals(applyReq.getRegenerateOrderedPlan())
                || !Boolean.TRUE.equals(applyReq.getRerunReview())) {
            throw new BusinessException(40001, "plan change apply requires regenerateOrderedPlan and rerunReview");
        }
        String proposalSource = RepairProposalTaxonomy.normalizeProposalSource(applyReq.getProposalSource());
        if (RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK.equals(proposalSource)) {
            if (applyReq.getUserGoalRequest() != null) {
                throw new BusinessException(40001, "review proposal must not contain userGoalRequest");
            }
            return;
        }
        if (!RepairProposalTaxonomy.ProposalSource.USER_GOAL.equals(proposalSource)) {
            throw new BusinessException(40001, "unsupported plan change proposal source: " + proposalSource);
        }
        UserGoalFixProposalReq userGoal = applyReq.getUserGoalRequest();
        if (userGoal == null) {
            throw new BusinessException(40001, "user_goal proposal requires userGoalRequest");
        }
        String strategy = RepairProposalTaxonomy.normalizeStrategy(userGoal.getGoalType());
        if (!RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(strategy)
                && !RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER.equals(strategy)) {
            throw new BusinessException(40001, "unsupported plan change goalType: " + userGoal.getGoalType());
        }
        if (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(strategy)
                && (userGoal.getTargetCount() == null || userGoal.getTargetCount() <= 0)) {
            throw new BusinessException(40001, "fill_to_count requires targetCount > 0");
        }
        String requirementError = ProjectedHardRequirementSupport.validate(userGoal.getRequirements());
        if (!Strings.isNullOrEmpty(requirementError)) {
            throw new BusinessException(40001, requirementError);
        }
        String priorityError = PriorityRuleSupport.validate(userGoal.getPriorityRules());
        if (!Strings.isNullOrEmpty(priorityError)) {
            throw new BusinessException(40001, priorityError);
        }
        if (userGoal.getTierQuotaGoal() != null) {
            try {
                TierAllocationSupport.compile(
                        null, userGoal.getTierQuotaGoal(), userGoal.getTargetCount());
            } catch (TierAllocationSupport.ContractException ex) {
                throw new BusinessException(40001,
                        ex.getReasonCode() + ": " + ex.getMessage());
            }
        }
        if (userGoal.getTierQuotaGoal() != null
                && ((userGoal.getRequirements() != null && !userGoal.getRequirements().isEmpty())
                || (userGoal.getPriorityRules() != null && !userGoal.getPriorityRules().isEmpty()))) {
            throw new BusinessException(40001,
                    "tierQuotaGoal cannot be combined with requirements or priorityRules");
        }
        if (userGoal.getTierQuotaGoal() != null
                && !RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(strategy)) {
            throw new BusinessException(40001, "tierQuotaGoal requires fill_to_count");
        }
        if (RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER.equals(strategy)
                && (userGoal.getPriorityRules() == null || userGoal.getPriorityRules().isEmpty())) {
            throw new BusinessException(40001, "prioritize_within_tier requires one priority rule");
        }
        if (!req.getExpectedPlanVersion().equals(userGoal.getSourceVersionGuard())) {
            throw new BusinessException(40001, "plan change source version must match expectedPlanVersion");
        }
    }

    private void requireText(String value, String field) {
        if (Strings.isNullOrEmpty(value) || Strings.isNullOrEmpty(value.trim())) {
            throw new BusinessException(40001, field + " is required");
        }
    }
}
