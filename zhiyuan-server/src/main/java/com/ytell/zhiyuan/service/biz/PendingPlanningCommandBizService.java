package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.UpdateScoreDetailRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftSelectReq;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
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
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
    /** add_units 新链路：加入已写、审查失败；必须抛异常回滚，不能提交半套。 */
    public static final int REVIEW_FAILED_CODE = 40907;
    /** add_units：调用方命令字段与 pending 冻结命令不一致（禁止换内容执行）。 */
    public static final int COMMAND_CONTENT_MISMATCH_CODE = 40908;
    public static final String APPLY_CONSTRAINT_AND_REGENERATE = "apply_constraint_and_regenerate";
    public static final String ADD_UNITS = "add_units";
    public static final String REPLACE_UNITS = "replace_units";
    public static final String APPLY_PLAN_CHANGE_PROPOSAL = "apply_plan_change_proposal";
    /** 补录成绩（score_update 动作族）：执行体与表单补录同一条核心（`ChatSessionBizService`）。 */
    public static final String UPDATE_SCORE_DETAIL = "update_score_detail";

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
    private ConversationAccessService conversationAccessService;
    @Autowired
    private UnifiedPlanPostconditionValidator postconditionValidator;

    @Transactional(rollbackFor = Exception.class)
    public PendingPlanningCommandRes execute(Long tenantId, Long chatSessionId,
                                             PendingPlanningCommandReq req) {
        validate(tenantId, chatSessionId, req);
        PendingConfirmationEntity pending = validatePendingOwner(tenantId, chatSessionId, req);
        Map<String, Object> frozenCommand = frozenCommand(pending);
        // 确认内容绑定：篡改比较必须在 replay/requestDigest 之前，否则会被 40903 截走。
        if (frozenCommand != null) {
            assertRequestMatchesFrozen(req, frozenCommand);
        }
        PlanningPendingCommandEntity existing = commandSharedService.getByOperationId(req.getOperationId());
        if (existing != null) {
            return replay(existing, tenantId, chatSessionId, req);
        }

        pending = validatePendingOwner(tenantId, chatSessionId, req);
        frozenCommand = frozenCommand(pending);
        if (frozenCommand != null) {
            assertRequestMatchesFrozen(req, frozenCommand);
        }
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

        PendingPlanningCommandRes result = executeCommand(
                tenantId, chatSessionId, req, currentVersion, frozenCommand);
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
                                                     int sourceVersion,
                                                     Map<String, Object> frozenCommand) {
        List<String> steps = new ArrayList<String>();
        PlanningStateDTO state;
        FixProposalApplyRes proposalApplyRes = null;
        // 有些命令的成功信号不是"计划结构变了"（补录成绩改的是成绩，方案原样不动），
        // 它们显式给出状态；其余命令保持原状（由满足度报告/业务码判）。
        String explicitStatus = null;
        Integer resultPlanVersionOverride = null;
        List<String> addUnitsAddedVolunteerIds = new ArrayList<String>();
        List<String> addUnitsAddedUnitIds = new ArrayList<String>();
        Integer addUnitsAddedVolunteerCount = null;
        Integer addUnitsAddedUnitCount = null;
        Integer addUnitsRemovedCount = null;
        Integer addUnitsTargetBefore = null;
        Integer addUnitsTargetAfter = null;
        ReviewStateDTO addUnitsReviewState = null;
        PlanChangePostconditionReportDTO addUnitsPostcondition = null;
        Integer constraintCountBefore = null;
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
                constraintCountBefore = UnifiedPlanPostconditionValidator.actualCount(
                        beforeRegenerate, UnifiedPlanPostconditionValidator.isMajorGroupMode(beforeRegenerate));
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

            if (ADD_UNITS.equals(req.getCommandType()) && frozenCommand != null) {
                // 新链路：只认 pending 冻结命令；请求层 volunteerIds 为空/被篡改都已在前置校验处理。
                AddUnitsExecution execution = executeAddUnitsWithFrozen(
                        tenantId, chatSessionId, frozenCommand, steps);
                state = execution.state;
                addUnitsAddedVolunteerIds = execution.addedVolunteerIds;
                addUnitsAddedUnitIds = execution.addedUnitIds;
                addUnitsAddedVolunteerCount = execution.addedVolunteerCount;
                addUnitsAddedUnitCount = execution.addedUnitCount;
                addUnitsRemovedCount = execution.removedVolunteerCount;
                addUnitsTargetBefore = execution.targetCountBefore;
                addUnitsTargetAfter = execution.targetCountAfter;
                addUnitsReviewState = execution.reviewState;
                addUnitsPostcondition = execution.postconditionReport;
                explicitStatus = "applied";
            } else {
                if (ADD_UNITS.equals(req.getCommandType())
                        && (req.getVolunteerIds() == null || req.getVolunteerIds().isEmpty())) {
                    throw new BusinessException(40001,
                            "add_units requires volunteerIds (frozenCommand missing)");
                }
                DraftSelectReq selectReq = new DraftSelectReq();
                selectReq.setVolunteerIds(req.getVolunteerIds());
                selectReq.setSource("pending_command");
                planningStateService.selectWorkingPlanItems(chatSessionId, selectReq);
                steps.add("working_plan_items_selected");

                state = planningStateService.generateOrderedPlan(tenantId, chatSessionId, forceOrderedRegenerate());
                steps.add("ordered_plan_regenerated");
            }
        } else if (APPLY_PLAN_CHANGE_PROPOSAL.equals(req.getCommandType())) {
            proposalApplyRes = planningStateService.applyFixProposal(
                    tenantId, chatSessionId, req.getProposalApply());
            state = proposalApplyRes.getState();
            steps.add("proposal_applied");
            steps.add("ordered_plan_regenerated");
            steps.add("review_rerun");
        } else if (UPDATE_SCORE_DETAIL.equals(req.getCommandType())) {
            // 执行体与 REST 补录完全同一条核心：合并 → 校验（失败回 110 并整体回滚）→
            // 落 userScoreDetail → 拉志愿数据 → 规划状态版本 +1 置 stale。
            // 归属用户从**会话行**解析：inner 端点没有登录态，见
            // `ConversationAccessService.requireSessionUserId`。
            Long ownerUserId = conversationAccessService.requireSessionUserId(tenantId, chatSessionId);
            if (ownerUserId == null) {
                throw new BusinessException(PendingConfirmationBizService.PENDING_MISMATCH_CODE,
                        "session owner is required for score update");
            }
            UpdateScoreDetailRes scoreUpdateRes = chatSessionBizService.updateScoreDetailForUser(
                    tenantId, chatSessionId, req.getScoreUpdate(), ownerUserId);
            state = planningStateService.getPlanningState(chatSessionId);
            steps.add("score_detail_updated");
            explicitStatus = "applied";
            resultPlanVersionOverride = scoreUpdateRes == null ? null : scoreUpdateRes.getPlanningVersion();
        } else {
            throw new BusinessException(40001, "unsupported commandType: " + req.getCommandType());
        }

        PendingPlanningCommandRes result = new PendingPlanningCommandRes();
        result.setOperationId(req.getOperationId());
        result.setPendingId(req.getPendingId());
        result.setCommandType(req.getCommandType());
        result.setSourcePlanVersion(sourceVersion);
        result.setResultPlanVersion(resultPlanVersionOverride != null
                ? resultPlanVersionOverride
                : (state.getVersion() == null ? 0 : state.getVersion()));
        result.setStatus(explicitStatus);
        result.setCompletedSteps(steps);
        if (addUnitsPostcondition != null) {
            result.setPostconditionReport(addUnitsPostcondition);
            result.setAddedVolunteerIds(addUnitsAddedVolunteerIds);
            result.setAddedUnitIds(addUnitsAddedUnitIds);
            result.setAddedVolunteerCount(addUnitsAddedVolunteerCount);
            result.setAddedUnitCount(addUnitsAddedUnitCount);
            result.setRemovedVolunteerCount(addUnitsRemovedCount);
            result.setTargetCountBefore(addUnitsTargetBefore);
            result.setTargetCountAfter(addUnitsTargetAfter);
            result.setReviewState(addUnitsReviewState);
        }
        if (APPLY_PLAN_CHANGE_PROPOSAL.equals(req.getCommandType())) {
            result.setPostconditionReport(postconditionValidator.validate(req, state, proposalApplyRes));
            steps.add("postcondition_verified");
        }
        if (APPLY_CONSTRAINT_AND_REGENERATE.equals(req.getCommandType())) {
            // 约束路以前没有满足度信号（DTO 里连 status 都没有 → 网关只能判 failed ✗）。
            // 补上，并且不满足就抛 40905 回滚：约束没生效就别改用户的方案 ✓。
            // 纯学费清理是**替换**语义：移出超预算条目后必须补足，数量缩水同样算不满足
            // （2026-10-18 真栈：51 组 → 36 组仍 satisfied=true ✗）。only_keep/exclude
            // 允许收缩，所以只在没有 constraintUpdate 的纯学费/金额约束上启用数量判据。
            boolean countPreserving = req.getConstraintUpdate() == null
                    && (req.getMinTuitionPerYear() != null || req.getMaxTuitionPerYear() != null);
            PlanChangePostconditionReportDTO constraintReport =
                    postconditionValidator.validateConstraintApply(
                            req.getCommandType(), state, constraintCountBefore, countPreserving);
            result.setPostconditionReport(constraintReport);
            result.setTargetCountBefore(constraintCountBefore);
            result.setTargetCountAfter(constraintReport.getActualCount());
            result.setShortage(constraintReport.getShortage());
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

    private PendingConfirmationEntity validatePendingOwner(Long tenantId, Long chatSessionId,
                                                           PendingPlanningCommandReq req) {
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
        return pending;
    }

    private Map<String, Object> frozenCommand(PendingConfirmationEntity pending) {
        if (pending == null || Strings.isNullOrEmpty(pending.getDataValue())) {
            return null;
        }
        try {
            JSONObject data = JSONObject.parseObject(pending.getDataValue());
            JSONObject frozen = data == null ? null : data.getJSONObject("frozenCommand");
            return frozen;
        } catch (Exception ex) {
            return null;
        }
    }

    /**
     * 确认内容绑定：调用方只带 5 个字段时容忍空；一旦带了命令字段，就必须与 frozen 一致。
     * 该比较在 replay/requestDigest 之前执行，篡改统一回 40908。
     */
    private void assertRequestMatchesFrozen(PendingPlanningCommandReq req, Map<String, Object> frozen) {
        if (req == null || !ADD_UNITS.equals(req.getCommandType()) || frozen == null) {
            return;
        }
        List<String> frozenIds = stringList(frozen.get("volunteerIds"));
        Set<String> requestedIds = new LinkedHashSet<String>(stringList(req.getVolunteerIds()));
        if (!requestedIds.isEmpty() && !requestedIds.equals(new LinkedHashSet<String>(frozenIds))) {
            throw new BusinessException(COMMAND_CONTENT_MISMATCH_CODE,
                    "command content mismatch: volunteerIds");
        }
        if (req.getRerunReview() != null
                && !req.getRerunReview().equals(Boolean.TRUE.equals(frozen.get("rerunReview")))) {
            throw new BusinessException(COMMAND_CONTENT_MISMATCH_CODE,
                    "command content mismatch: rerunReview");
        }
    }

    private AddUnitsExecution executeAddUnitsWithFrozen(Long tenantId, Long chatSessionId,
                                                        Map<String, Object> frozen,
                                                        List<String> steps) {
        List<String> requested = stringList(frozen.get("volunteerIds"));
        if (requested.isEmpty()) {
            throw new BusinessException(40001, "add_units requires volunteerIds (frozenCommand empty)");
        }
        Integer override = intValue(frozen.get("targetCountOverride"));
        boolean rerunReview = Boolean.TRUE.equals(frozen.get("rerunReview"));
        PlanningStateDTO before = planningStateService.getPlanningState(chatSessionId);
        boolean unitMode = isUnitMode(before);
        Set<String> beforeVolunteerIds = workingVolunteerIds(before);
        Set<String> beforeUnitIds = workingUnitIds(before);
        int beforeCount = unitMode ? beforeUnitIds.size() : beforeVolunteerIds.size();

        if (override != null) {
            planningStateService.updateSelectionTargetCount(chatSessionId, override);
            steps.add("selection_target_updated");
        }
        PlanningStateDTO current = planningStateService.getPlanningState(chatSessionId);
        Set<String> effectiveVolunteerIds = new LinkedHashSet<String>();
        for (CandidateItemDTO candidate : planningStateService.resolveEffectiveCandidatesForProposal(current)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                effectiveVolunteerIds.add(candidate.getVolunteerId());
            }
        }
        for (String volunteerId : requested) {
            if (!effectiveVolunteerIds.contains(volunteerId)) {
                throw new BusinessException(POSTCONDITION_FAILED_CODE,
                        "add_units target_not_found: " + volunteerId
                                + " (candidate pool changed or target no longer eligible)");
            }
        }

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(requested);
        selectReq.setSource("pending_command");
        planningStateService.selectWorkingPlanItems(chatSessionId, selectReq);
        steps.add("working_plan_items_selected");
        PlanningStateDTO state = planningStateService.generateOrderedPlan(
                tenantId, chatSessionId, forceOrderedRegenerate());
        steps.add("ordered_plan_regenerated");

        Set<String> afterVolunteerIds = workingVolunteerIds(state);
        Set<String> afterUnitIds = workingUnitIds(state);
        Set<String> orderedVolunteerIds = orderedVolunteerIds(state);
        Set<String> orderedUnitIds = orderedUnitIds(state);

        for (String volunteerId : requested) {
            if (!afterVolunteerIds.contains(volunteerId) || !orderedVolunteerIds.contains(volunteerId)) {
                throw new BusinessException(POSTCONDITION_FAILED_CODE,
                        "add_units postcondition failed: requested item missing " + volunteerId);
            }
        }
        Set<String> removed = new LinkedHashSet<String>(beforeVolunteerIds);
        removed.removeAll(afterVolunteerIds);
        if (!removed.isEmpty()) {
            throw new BusinessException(POSTCONDITION_FAILED_CODE,
                    "add_units postcondition failed: existing items removed " + removed.size());
        }
        for (String volunteerId : beforeVolunteerIds) {
            if (!afterVolunteerIds.contains(volunteerId) || !orderedVolunteerIds.contains(volunteerId)) {
                throw new BusinessException(POSTCONDITION_FAILED_CODE,
                        "add_units postcondition failed: existing item missing " + volunteerId);
            }
        }
        Set<String> afterUnits = new LinkedHashSet<String>(afterUnitIds);
        afterUnits.removeAll(beforeUnitIds);
        int afterCount = unitMode ? afterUnitIds.size() : afterVolunteerIds.size();
        if (override != null && afterCount != override) {
            throw new BusinessException(POSTCONDITION_FAILED_CODE,
                    "add_units postcondition failed: target=" + override + " actual=" + afterCount);
        }

        ReviewStateDTO reviewState = null;
        if (rerunReview) {
            try {
                reviewState = planningStateService.runReview(tenantId, chatSessionId);
            } catch (Exception ex) {
                // 不能 catch-return：@Transactional 会把已加入的方案提交。必须抛出回滚。
                throw new BusinessException(REVIEW_FAILED_CODE,
                        "review_failed: " + (ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage()));
            }
            state = planningStateService.getPlanningState(chatSessionId);
            steps.add("review_rerun");
        }

        AddUnitsExecution execution = new AddUnitsExecution();
        execution.state = state;
        Set<String> addedVolunteerIds = new LinkedHashSet<String>(afterVolunteerIds);
        addedVolunteerIds.removeAll(beforeVolunteerIds);
        execution.addedVolunteerIds = new ArrayList<String>(addedVolunteerIds);
        execution.addedUnitIds = new ArrayList<String>(afterUnits);
        execution.addedVolunteerCount = addedVolunteerIds.size();
        execution.addedUnitCount = afterUnits.size();
        execution.removedVolunteerCount = removed.size();
        execution.targetCountBefore = beforeCount;
        execution.targetCountAfter = override != null ? override : afterCount;
        execution.reviewState = reviewState;

        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setGoalType("add_units");
        report.setCountMode(unitMode ? "unit" : "volunteer");
        report.setTargetCount(execution.targetCountAfter);
        report.setActualCount(afterCount);
        report.setAddedVolunteerCount(execution.addedVolunteerCount);
        report.setAffectedUnitCount(execution.addedUnitCount);
        report.setRemovedVolunteerCount(execution.removedVolunteerCount);
        report.setSatisfied(true);
        execution.postconditionReport = report;
        return execution;
    }

    private static boolean isUnitMode(PlanningStateDTO state) {
        return state != null && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
    }

    private static Set<String> workingVolunteerIds(PlanningStateDTO state) {
        Set<String> result = new LinkedHashSet<String>();
        if (state == null || state.getWorkingPlanState() == null) {
            return result;
        }
        for (DraftItemDTO item : defaultList(state.getWorkingPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                result.add(item.getVolunteerId());
            }
        }
        for (DraftUnitDTO unit : defaultList(state.getWorkingPlanState().getUnits())) {
            for (PlanningUnitMajorDTO major : defaultList(unit == null ? null : unit.getMajorItems())) {
                if (major != null && !Strings.isNullOrEmpty(major.getVolunteerId())) {
                    result.add(major.getVolunteerId());
                }
            }
        }
        return result;
    }

    private static Set<String> workingUnitIds(PlanningStateDTO state) {
        Set<String> result = new LinkedHashSet<String>();
        if (state == null || state.getWorkingPlanState() == null) {
            return result;
        }
        for (DraftUnitDTO unit : defaultList(state.getWorkingPlanState().getUnits())) {
            if (unit != null && !Strings.isNullOrEmpty(unit.getUnitId())) {
                result.add(unit.getUnitId());
            }
        }
        return result;
    }

    private static Set<String> orderedVolunteerIds(PlanningStateDTO state) {
        Set<String> result = new LinkedHashSet<String>();
        if (state == null || state.getOrderedPlanState() == null) {
            return result;
        }
        for (OrderedItemDTO item : defaultList(state.getOrderedPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                result.add(item.getVolunteerId());
            }
        }
        for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
            for (PlanningUnitMajorDTO major : defaultList(unit == null ? null : unit.getMajorItems())) {
                if (major != null && !Strings.isNullOrEmpty(major.getVolunteerId())) {
                    result.add(major.getVolunteerId());
                }
            }
        }
        return result;
    }

    private static Set<String> orderedUnitIds(PlanningStateDTO state) {
        Set<String> result = new LinkedHashSet<String>();
        if (state == null || state.getOrderedPlanState() == null) {
            return result;
        }
        for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
            if (unit != null && !Strings.isNullOrEmpty(unit.getUnitId())) {
                result.add(unit.getUnitId());
            }
        }
        return result;
    }

    private static List<String> stringList(Object value) {
        List<String> result = new ArrayList<String>();
        if (value instanceof List) {
            for (Object item : (List<?>) value) {
                if (item != null && !Strings.isNullOrEmpty(String.valueOf(item))) {
                    result.add(String.valueOf(item));
                }
            }
        }
        return result;
    }

    private static Integer intValue(Object value) {
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        if (value == null) {
            return null;
        }
        try {
            return Integer.valueOf(String.valueOf(value));
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
    }

    private static final class AddUnitsExecution {
        private PlanningStateDTO state;
        private List<String> addedVolunteerIds = new ArrayList<String>();
        private List<String> addedUnitIds = new ArrayList<String>();
        private Integer addedVolunteerCount;
        private Integer addedUnitCount;
        private Integer removedVolunteerCount;
        private Integer targetCountBefore;
        private Integer targetCountAfter;
        private ReviewStateDTO reviewState;
        private PlanChangePostconditionReportDTO postconditionReport;
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
        compact.setStatus(source.getStatus());
        compact.setCompletedSteps(new ArrayList<String>(source.getCompletedSteps()));
        compact.setPostconditionReport(source.getPostconditionReport());
        compact.setAddedVolunteerIds(new ArrayList<String>(source.getAddedVolunteerIds()));
        compact.setAddedUnitIds(new ArrayList<String>(source.getAddedUnitIds()));
        compact.setAddedVolunteerCount(source.getAddedVolunteerCount());
        compact.setAddedUnitCount(source.getAddedUnitCount());
        compact.setRemovedVolunteerCount(source.getRemovedVolunteerCount());
        compact.setTargetCountBefore(source.getTargetCountBefore());
        compact.setTargetCountAfter(source.getTargetCountAfter());
        compact.setReviewState(source.getReviewState());
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
            stable.setScoreUpdate(req.getScoreUpdate());
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
                && !APPLY_PLAN_CHANGE_PROPOSAL.equals(req.getCommandType())
                && !UPDATE_SCORE_DETAIL.equals(req.getCommandType())) {
            throw new BusinessException(40001, "unsupported commandType: " + req.getCommandType());
        }
        if (UPDATE_SCORE_DETAIL.equals(req.getCommandType()) && req.getScoreUpdate() == null) {
            throw new BusinessException(40001, "update_score_detail requires scoreUpdate");
        }
        // add_units 新链路只发 5 个字段（commandType/pendingId/operationId/claimToken/
        // expectedPlanVersion），volunteerIds 由 Java 从已认领 pending 的 frozenCommand
        // 读取；请求层允许空/省略。legacy 仍带 volunteerIds，行为不变。
        // 真正的“空且没有 frozen”在 execute 读取 pending 后再拒绝。
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
