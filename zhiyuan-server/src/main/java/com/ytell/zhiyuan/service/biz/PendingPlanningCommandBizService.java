package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftSelectReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.RepairReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
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
                state = planningStateService.generateOrderedPlan(tenantId, chatSessionId, forceOrderedRegenerate());
                steps.add("ordered_plan_regenerated");
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
            result.setPostconditionReport(verifyPlanChangePostcondition(req, state, proposalApplyRes));
            steps.add("postcondition_verified");
        }
        result.setPlanningState(state);
        result.setReplayed(false);
        return result;
    }

    private PlanChangePostconditionReportDTO verifyPlanChangePostcondition(PendingPlanningCommandReq req,
                                                                           PlanningStateDTO state,
                                                                           FixProposalApplyRes applyRes) {
        UserGoalFixProposalReq userGoal = req.getProposalApply().getUserGoalRequest();
        if (userGoal == null) {
            return verifyReviewFixPostcondition(req, applyRes);
        }
        boolean countRequired = RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(
                RepairProposalTaxonomy.normalizeStrategy(userGoal.getGoalType()));
        Integer targetCount = userGoal.getTargetCount();
        boolean majorGroupMode = state != null && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        int actualCount;
        if (majorGroupMode) {
            actualCount = state != null && state.getOrderedPlanState() != null
                    && state.getOrderedPlanState().getUnits() != null
                    && !state.getOrderedPlanState().getUnits().isEmpty()
                    ? state.getOrderedPlanState().getUnits().size()
                    : state != null && state.getWorkingPlanState() != null
                    && state.getWorkingPlanState().getUnits() != null
                    ? state.getWorkingPlanState().getUnits().size() : 0;
        } else {
            actualCount = state != null && state.getOrderedPlanState() != null
                    && state.getOrderedPlanState().getItems() != null
                    && !state.getOrderedPlanState().getItems().isEmpty()
                    ? state.getOrderedPlanState().getItems().size()
                    : state != null && state.getWorkingPlanState() != null
                    && state.getWorkingPlanState().getItems() != null
                    ? state.getWorkingPlanState().getItems().size() : 0;
        }
        Integer persistedTarget = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        boolean persistTargetCount = !Boolean.FALSE.equals(userGoal.getPersistTargetCount());
        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setGoalType(userGoal.getGoalType());
        report.setCountMode(majorGroupMode ? "unit" : "volunteer");
        report.setTargetCount(targetCount);
        report.setActualCount(actualCount);
        List<CandidateItemDTO> planCandidates = postconditionPlanCandidates(state, majorGroupMode);
        int satisfiedRequirements = 0;
        for (UserGoalFixProposalReq.RequirementDTO requirement : defaultList(userGoal.getRequirements())) {
            PlanChangePostconditionReportDTO.RequirementResultDTO requirementResult =
                    new PlanChangePostconditionReportDTO.RequirementResultDTO();
            requirementResult.setKind(requirement.getKind());
            requirementResult.setDomain(requirement.getDomain());
            requirementResult.setKey(requirement.getKey());
            requirementResult.setValues(defaultList(requirement.getValues()));
            if (ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind())) {
                requirementResult.setMinCount(CoverageRequirementSupport.minCount(requirement));
            }
            int matchedCount = postconditionRequirementMatchedCount(
                    state, majorGroupMode, planCandidates, requirement);
            requirementResult.setMatchedCount(matchedCount);
            boolean planSatisfied;
            if (ProjectedHardRequirementSupport.KIND_EXCLUDE.equalsIgnoreCase(requirement.getKind())) {
                planSatisfied = planCandidates.stream()
                        .noneMatch(candidate -> ProjectedHardRequirementSupport.matches(candidate, requirement));
            } else if (ProjectedHardRequirementSupport.KIND_ONLY_KEEP.equalsIgnoreCase(requirement.getKind())) {
                planSatisfied = !planCandidates.isEmpty() && planCandidates.stream()
                        .allMatch(candidate -> ProjectedHardRequirementSupport.matches(candidate, requirement));
            } else if (ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind())) {
                planSatisfied = matchedCount >= CoverageRequirementSupport.minCount(requirement);
            } else {
                planSatisfied = false;
            }
            boolean persisted = ProjectedHardRequirementSupport.isPersisted(state, requirement);
            boolean requirementSatisfied = planSatisfied && persisted;
            requirementResult.setPlanSatisfied(planSatisfied);
            requirementResult.setPersisted(persisted);
            requirementResult.setSatisfied(requirementSatisfied);
            report.getRequirementResults().add(requirementResult);
            if (requirementSatisfied) {
                satisfiedRequirements++;
            }
        }
        report.setRequirementCount(report.getRequirementResults().size());
        report.setSatisfiedRequirementCount(satisfiedRequirements);
        boolean requirementsSatisfied = satisfiedRequirements == report.getRequirementResults().size();
        int satisfiedPriorityRules = 0;
        List<CandidateItemDTO> priorityCandidates = state == null || state.getCandidatePoolState() == null
                ? new ArrayList<CandidateItemDTO>() : defaultList(state.getCandidatePoolState().getItems());
        for (PriorityRuleDTO rule : defaultList(userGoal.getPriorityRules())) {
            PriorityRuleSupport.Analysis analysis = PriorityRuleSupport.analyze(state, priorityCandidates, rule);
            PlanChangePostconditionReportDTO.PriorityRuleResultDTO ruleResult =
                    new PlanChangePostconditionReportDTO.PriorityRuleResultDTO();
            ruleResult.setDomain(rule.getDomain());
            ruleResult.setKey(rule.getKey());
            ruleResult.setValues(defaultList(rule.getValues()));
            ruleResult.setOrderingTarget(rule.getOrderingTarget());
            ruleResult.setScope(rule.getScope());
            ruleResult.setMatchedCount(analysis.getMatchedCount());
            ruleResult.setInversionCount(analysis.getInversionCount());
            boolean planSatisfied = analysis.getEntityCount() > 0
                    && analysis.getMatchedCount() > 0 && !analysis.hasMissingTier()
                    && analysis.getInversionCount() == 0;
            boolean persisted = PriorityRuleSupport.isPersisted(state, rule);
            boolean satisfied = planSatisfied && persisted;
            ruleResult.setPlanSatisfied(planSatisfied);
            ruleResult.setPersisted(persisted);
            ruleResult.setSatisfied(satisfied);
            report.getPriorityRuleResults().add(ruleResult);
            if (satisfied) {
                satisfiedPriorityRules++;
            }
        }
        report.setPriorityRuleCount(report.getPriorityRuleResults().size());
        report.setSatisfiedPriorityRuleCount(satisfiedPriorityRules);
        boolean priorityRulesSatisfied = satisfiedPriorityRules == report.getPriorityRuleResults().size();
        TierQuotaGoalDTO tierQuota = userGoal.getTierQuotaGoal();
        boolean tierQuotaSatisfied = true;
        if (tierQuota != null) {
            List<UserGoalFixProposalReq.RequirementDTO> quotaRequirements =
                    TierQuotaSupport.syntheticRequirements(tierQuota);
            int actualSprintCount = postconditionRequirementMatchedCount(
                    state, majorGroupMode, planCandidates, quotaRequirements.get(0));
            int actualStableCount = postconditionRequirementMatchedCount(
                    state, majorGroupMode, planCandidates, quotaRequirements.get(1));
            int actualProtectCount = postconditionRequirementMatchedCount(
                    state, majorGroupMode, planCandidates, quotaRequirements.get(2));
            PlanChangePostconditionReportDTO.TierQuotaResultDTO quotaResult =
                    new PlanChangePostconditionReportDTO.TierQuotaResultDTO();
            quotaResult.setType(tierQuota.getType());
            quotaResult.setSprintCount(tierQuota.getSprintCount());
            quotaResult.setStableCount(tierQuota.getStableCount());
            quotaResult.setProtectCount(tierQuota.getProtectCount());
            quotaResult.setActualSprintCount(actualSprintCount);
            quotaResult.setActualStableCount(actualStableCount);
            quotaResult.setActualProtectCount(actualProtectCount);
            boolean quotaPlanSatisfied = tierQuota.getSprintCount() != null
                    && tierQuota.getStableCount() != null && tierQuota.getProtectCount() != null
                    && tierQuota.getSprintCount() == actualSprintCount
                    && tierQuota.getStableCount() == actualStableCount
                    && tierQuota.getProtectCount() == actualProtectCount;
            boolean quotaPersisted = TierQuotaSupport.isPersisted(state, tierQuota);
            tierQuotaSatisfied = quotaPlanSatisfied && quotaPersisted;
            quotaResult.setPlanSatisfied(quotaPlanSatisfied);
            quotaResult.setPersisted(quotaPersisted);
            quotaResult.setSatisfied(tierQuotaSatisfied);
            report.setTierQuotaResult(quotaResult);
        }
        boolean countSatisfied = !countRequired || (targetCount != null
                && actualCount == targetCount
                && (!persistTargetCount || targetCount.equals(persistedTarget)));
        report.setSatisfied(countSatisfied && requirementsSatisfied && priorityRulesSatisfied && tierQuotaSatisfied);
        if (!Boolean.TRUE.equals(report.getSatisfied())) {
            throw new BusinessException(POSTCONDITION_FAILED_CODE,
                    "plan change postcondition failed: target=" + targetCount
                            + " actual=" + actualCount + " persistedTarget=" + persistedTarget
                            + " requirements=" + satisfiedRequirements + "/" + report.getRequirementCount()
                            + " priorityRules=" + satisfiedPriorityRules + "/" + report.getPriorityRuleCount()
                            + " tierQuota=" + tierQuotaSatisfied);
        }
        return report;
    }

    private PlanChangePostconditionReportDTO verifyReviewFixPostcondition(PendingPlanningCommandReq req,
                                                                           FixProposalApplyRes applyRes) {
        FixProposalApplyReq applyReq = req.getProposalApply();
        FixProposalDTO proposal = applyRes == null ? null : applyRes.getProposal();
        RepairReportDTO repairReport = applyRes == null ? null : applyRes.getRepairReport();
        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setProposalSource(proposal == null ? null : proposal.getProposalSource());
        report.setProposalId(proposal == null ? null : proposal.getProposalId());
        report.setProposalStrategy(proposal == null ? null : proposal.getStrategy());
        report.setGoalType(proposal == null ? null : proposal.getStrategy());
        if (repairReport != null) {
            report.setSourceReviewIssueCodes(defaultList(repairReport.getSourceCheckCodes()));
            report.setPostValidationPassed(repairReport.getPostValidationPassed());
            report.setAppliedActionCount(repairReport.getAppliedActionCount());
            report.setAffectedUnitCount(repairReport.getAffectedUnitCount());
            report.setAddedVolunteerCount(repairReport.getAddedVolunteerCount());
            report.setRemovedVolunteerCount(repairReport.getRemovedVolunteerCount());
        }
        boolean applied = applyRes != null && "applied".equalsIgnoreCase(applyRes.getStatus());
        boolean proposalMatches = proposal != null && applyReq != null
                && applyReq.getProposalId() != null
                && applyReq.getProposalId().equals(proposal.getProposalId())
                && RepairProposalTaxonomy.normalizeProposalSource(applyReq.getProposalSource()).equals(
                RepairProposalTaxonomy.normalizeProposalSource(proposal.getProposalSource()));
        boolean postValidationPassed = repairReport != null
                && Boolean.TRUE.equals(repairReport.getPostValidationPassed());
        report.setSatisfied(applied && proposalMatches && postValidationPassed);
        if (!Boolean.TRUE.equals(report.getSatisfied())) {
            throw new BusinessException(POSTCONDITION_FAILED_CODE,
                    "review fix postcondition failed: applied=" + applied
                            + " proposalMatches=" + proposalMatches
                            + " postValidationPassed=" + postValidationPassed);
        }
        return report;
    }

    private int postconditionRequirementMatchedCount(
            PlanningStateDTO state,
            boolean majorGroupMode,
            List<CandidateItemDTO> planCandidates,
            UserGoalFixProposalReq.RequirementDTO requirement) {
        if (!majorGroupMode
                || !ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind())) {
            return (int) defaultList(planCandidates).stream()
                    .filter(candidate -> ProjectedHardRequirementSupport.matches(candidate, requirement))
                    .count();
        }
        List<CandidateItemDTO> pool = state == null || state.getCandidatePoolState() == null
                ? new ArrayList<CandidateItemDTO>() : defaultList(state.getCandidatePoolState().getItems());
        List<OrderedUnitDTO> orderedUnits = state == null || state.getOrderedPlanState() == null
                ? new ArrayList<OrderedUnitDTO>() : defaultList(state.getOrderedPlanState().getUnits());
        if (!orderedUnits.isEmpty()) {
            int matchedUnits = 0;
            for (OrderedUnitDTO unit : orderedUnits) {
                List<PlanningUnitMajorDTO> majors = defaultList(unit == null ? null : unit.getMajorItems());
                boolean matched = majors.isEmpty()
                        ? ProjectedHardRequirementSupport.matches(
                        postconditionCandidate(unit, null), requirement)
                        : majors.stream().anyMatch(major -> {
                            CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                                    pool, major == null ? null : major.getVolunteerId());
                            return ProjectedHardRequirementSupport.matches(
                                    candidate == null ? postconditionCandidate(unit, major) : candidate,
                                    requirement);
                        });
                if (matched) {
                    matchedUnits++;
                }
            }
            return matchedUnits;
        }
        List<String> matchedUnitIds = new ArrayList<String>();
        for (CandidateItemDTO candidate : defaultList(planCandidates)) {
            if (!ProjectedHardRequirementSupport.matches(candidate, requirement)) {
                continue;
            }
            String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            if (!Strings.isNullOrEmpty(unitId) && !matchedUnitIds.contains(unitId)) {
                matchedUnitIds.add(unitId);
            }
        }
        return matchedUnitIds.size();
    }

    private List<CandidateItemDTO> postconditionPlanCandidates(PlanningStateDTO state, boolean majorGroupMode) {
        List<CandidateItemDTO> result = new ArrayList<CandidateItemDTO>();
        List<CandidateItemDTO> pool = state == null || state.getCandidatePoolState() == null
                ? new ArrayList<CandidateItemDTO>() : defaultList(state.getCandidatePoolState().getItems());
        if (majorGroupMode && state != null && state.getOrderedPlanState() != null) {
            for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
                for (PlanningUnitMajorDTO major : defaultList(unit == null ? null : unit.getMajorItems())) {
                    CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                            pool, major == null ? null : major.getVolunteerId());
                    result.add(candidate == null ? postconditionCandidate(unit, major) : candidate);
                }
            }
            return result;
        }
        if (state != null && state.getOrderedPlanState() != null
                && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()) {
            for (OrderedItemDTO item : defaultList(state.getOrderedPlanState().getItems())) {
                CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                        pool, item == null ? null : item.getVolunteerId());
                if (candidate != null) {
                    result.add(candidate);
                    continue;
                }
                CandidateItemDTO fallback = new CandidateItemDTO();
                fallback.setVolunteerId(item == null ? null : item.getVolunteerId());
                fallback.setSchoolName(item == null ? null : item.getSchoolName());
                fallback.setDisplaySchoolName(item == null ? null : item.getSchoolName());
                fallback.setMajorName(item == null ? null : item.getMajorName());
                result.add(fallback);
            }
            return result;
        }
        if (state != null && state.getWorkingPlanState() != null) {
            for (DraftItemDTO item : defaultList(state.getWorkingPlanState().getItems())) {
                CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                        pool, item == null ? null : item.getVolunteerId());
                if (candidate != null) {
                    result.add(candidate);
                }
            }
        }
        return result;
    }

    private CandidateItemDTO postconditionCandidate(OrderedUnitDTO unit, PlanningUnitMajorDTO major) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(major == null ? null : major.getVolunteerId());
        candidate.setPlanSchoolDataId(unit == null ? null : unit.getUnitId());
        candidate.setSchoolName(unit == null ? null : unit.getSchoolName());
        candidate.setDisplaySchoolName(unit == null ? null : unit.getSchoolName());
        candidate.setProvinceName(unit == null ? null : unit.getProvinceName());
        candidate.setCityName(unit == null ? null : unit.getCityName());
        candidate.setSchoolNature(unit == null ? null : unit.getSchoolNature());
        candidate.setSchoolCategory(unit == null ? null : unit.getSchoolCategory());
        candidate.setSchoolLevel(unit == null ? null : unit.getSchoolLevel());
        candidate.setMajorName(major == null ? null : major.getMajorName());
        candidate.setMajorCategoryId(major == null ? null : major.getMajorCategoryId());
        candidate.setMajorSubCategoryId(major == null ? null : major.getMajorSubCategoryId());
        candidate.setMajorPlanTags(major == null ? new ArrayList<String>() : defaultList(major.getMajorPlanTags()));
        candidate.setReasonCodes(major == null ? new ArrayList<String>() : defaultList(major.getReasonCodes()));
        candidate.setTuitionPerYear(major == null ? null : major.getTuitionPerYear());
        return candidate;
    }

    private <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
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
        String tierQuotaError = TierQuotaSupport.validate(userGoal.getTierQuotaGoal(), userGoal.getTargetCount());
        if (!Strings.isNullOrEmpty(tierQuotaError)) {
            throw new BusinessException(40001, tierQuotaError);
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
