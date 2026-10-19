package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.serializer.SerializerFeature;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FindingPostconditionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

final class DirectReviewPreviewPlanner {
    private final FindingPostconditionEvaluator postconditionEvaluator = new FindingPostconditionEvaluator();

    FixProposalDTO plan(PlanningStateDTO state, List<CandidateItemDTO> candidates,
                        EvaluationFindingDTO finding,
                        Function<PlanningStateDTO, ReviewStateDTO> reevaluate) {
        PlanCommandDTO command = finding == null ? null : finding.getSuggestedCommand();
        if (command == null || !"probability_inversion".equals(finding.getCode())
                || !"fail".equals(finding.getResultStatus())
                || !RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY.equals(command.getStrategy())) {
            return null;
        }
        FixProposalDTO proposal = proposal(state, finding, command);
        if (state == null || state.getCandidatePoolState() == null || state.getWorkingPlanState() == null
                || state.getOrderedPlanState() == null || reevaluate == null
                || Strings.isNullOrEmpty(command.getEvaluationVersion())
                || Strings.isNullOrEmpty(command.getCommandDigest())) {
            return blocked(proposal, "review_fix_evaluation_unavailable");
        }
        if ("majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel())
                || !safeList(state.getWorkingPlanState().getUnits()).isEmpty()
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty()
                || !PriorityRuleSupport.confirmedRules(state).isEmpty()) {
            return blocked(proposal, "review_fix_direct_unsupported");
        }
        List<DraftItemDTO> selected = state.getWorkingPlanState().getItems();
        List<OrderedItemDTO> ordered = new ArrayList<OrderedItemDTO>(safeList(state.getOrderedPlanState().getItems()));
        if (selected == null || selected.isEmpty() || ordered.isEmpty()
                || ordered.stream().anyMatch(item -> item == null || item.getPosition() == null)
                || selected.stream().anyMatch(item -> item == null || Strings.isNullOrEmpty(item.getVolunteerId()))) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        ordered.sort(Comparator.comparing(OrderedItemDTO::getPosition));
        Set<String> selectedIds = new LinkedHashSet<String>();
        for (DraftItemDTO item : selected) {
            if (Boolean.TRUE.equals(item.getLocked())) {
                return blocked(proposal, "review_fix_order_locked");
            }
            if (!selectedIds.add(item.getVolunteerId())) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
        }
        Map<String, OrderedItemDTO> orderedById = new LinkedHashMap<String, OrderedItemDTO>();
        for (int index = 0; index < ordered.size(); index++) {
            OrderedItemDTO item = ordered.get(index);
            if (Boolean.TRUE.equals(item.getLocked()) || Boolean.TRUE.equals(item.getPinned())
                    || item.getPinnedPosition() != null) {
                return blocked(proposal, "review_fix_order_locked");
            }
            if (Strings.isNullOrEmpty(item.getVolunteerId()) || item.getPosition() != index + 1
                    || orderedById.put(item.getVolunteerId(), item) != null) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
        }
        if (!selectedIds.equals(orderedById.keySet())) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        Set<String> authorized = new LinkedHashSet<String>();
        if (command.getReorderTargets() == null || command.getReorderTargets().isEmpty()) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        for (EvaluationEntryRefDTO ref : command.getReorderTargets()) {
            if (ref == null || !"volunteer".equals(ref.getLevel()) || !selectedIds.contains(ref.getId())
                    || !authorized.add(ref.getId())) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
        }
        Map<String, CandidateItemDTO> selectedFacts = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : candidates == null ? new ArrayList<CandidateItemDTO>() : candidates) {
            if (candidate != null && selectedIds.contains(candidate.getVolunteerId())
                    && selectedFacts.put(candidate.getVolunteerId(), candidate) != null) {
                return blocked(proposal, "review_fix_facts_incomplete");
            }
        }
        Map<String, Double> ratios = new LinkedHashMap<String, Double>();
        for (String identity : selectedIds) {
            CandidateItemDTO fact = selectedFacts.get(identity);
            Double ratio = fact == null ? null
                    : fact.getAdmissionRatio() != null ? fact.getAdmissionRatio() : fact.getSchoolEnrollRatio();
            if (ratio == null || !Double.isFinite(ratio)) {
                return blocked(proposal, "review_fix_facts_incomplete");
            }
            if (!RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(fact, state)) {
                return blocked(proposal, "hard_constraints_unsatisfied");
            }
            if (!hardFactsComplete(fact, state)) {
                return blocked(proposal, "review_fix_facts_incomplete");
            }
            ratios.put(identity, ratio);
        }
        List<PlanOrderingEngine.OrderEntry> entries = new ArrayList<PlanOrderingEngine.OrderEntry>();
        for (OrderedItemDTO item : ordered) {
            entries.add(new PlanOrderingEngine.OrderEntry(item.getVolunteerId(), item.getTier(), false,
                    !authorized.contains(item.getVolunteerId())));
        }
        PlanOrderingEngine.OrderResult result = PlanOrderingEngine.orderByProbability(entries, ratios);
        PlanningStateDTO after = copy(state, PlanningStateDTO.class);
        List<OrderedItemDTO> finalOrder = new ArrayList<OrderedItemDTO>();
        for (String identity : result.orderedIds) {
            OrderedItemDTO item = copy(orderedById.get(identity), OrderedItemDTO.class);
            item.setPosition(finalOrder.size() + 1);
            finalOrder.add(item);
        }
        after.getOrderedPlanState().setItems(finalOrder);
        ReviewStateDTO afterReview;
        try {
            afterReview = reevaluate.apply(copy(after, PlanningStateDTO.class));
        } catch (RuntimeException unavailable) {
            return blocked(proposal, "review_fix_evaluation_unavailable");
        }
        FindingPostconditionDTO postcondition = postconditionEvaluator.evaluate(finding.getCode(), afterReview);
        proposal.setFindingPostcondition(postcondition);
        if (!Boolean.TRUE.equals(postcondition.getSatisfied())) {
            return blocked(proposal, postcondition.getReasonCode());
        }
        FrozenReviewPlanDTO frozen = new FrozenReviewPlanDTO();
        frozen.setWorkingPlan(copy(after.getWorkingPlanState(), DraftPlanStateDTO.class));
        frozen.setOrderedPlan(copy(after.getOrderedPlanState(), OrderedPlanStateDTO.class));
        frozen.setSelectedEntityIds(new ArrayList<String>(selectedIds));
        frozen.setOrderedEntityIds(new ArrayList<String>(result.orderedIds));
        for (String identity : selectedIds) {
            frozen.getSelectedFacts().add(copy(selectedFacts.get(identity), CandidateItemDTO.class));
        }
        frozen.setFactsDigest(digest(frozen.getSelectedFacts()));
        proposal.setFrozenReviewPlan(frozen);
        proposal.setCanonicalObjectiveDigest(PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest());
        proposal.setPlanContentDigest(digest(Arrays.asList(state.getWorkingPlanState(), state.getOrderedPlanState())));
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("reorder_volunteers");
        action.setLevel("volunteer");
        action.setSourceCheckCode(finding.getCode());
        action.setVolunteerIds(new ArrayList<String>(result.orderedIds));
        proposal.getActions().add(action);
        proposal.getDryRunResult().setBeforeVolunteerTotal(selectedIds.size());
        proposal.getDryRunResult().setAfterVolunteerTotal(selectedIds.size());
        proposal.getDryRunResult().setBeforeVolunteerIds(new LinkedHashSet<String>(selectedIds));
        proposal.getDryRunResult().setAfterVolunteerIds(new LinkedHashSet<String>(selectedIds));
        proposal.getDryRunResult().setStatus("preview_only");
        proposal.setProposalId("fp_" + digest(Arrays.asList(command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), command.getCommandDigest(), proposal.getActions())).substring(0, 16));
        proposal.setPreviewDigest(digest(Arrays.asList(proposal.getProposalId(), command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), proposal.getCanonicalObjectiveDigest(), frozen,
                proposal.getActions(), proposal.getDryRunResult(), postcondition)));
        proposal.setBlockingReason("review_fix_prepare_unavailable");
        proposal.getBlockingReasonCodes().add("review_fix_prepare_unavailable");
        return proposal;
    }

    private FixProposalDTO proposal(PlanningStateDTO state, EvaluationFindingDTO finding, PlanCommandDTO command) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStatus("preview_only");
        proposal.setRequiresConfirmation(false);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setStrategy(command.getStrategy());
        proposal.setSourceStrategy(command.getSourceStrategy());
        proposal.setFindingCode(finding.getCode());
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle("录取率倒挂排序预览");
        proposal.setSummary("只读冻结预览；确认执行入口尚未启用。");
        proposal.getSourceCheckCodes().add(finding.getCode());
        return proposal;
    }

    private FixProposalDTO blocked(FixProposalDTO proposal, String reason) {
        proposal.setBlockingReason(reason);
        proposal.getBlockingReasonCodes().add(reason);
        proposal.getDryRunResult().setStatus("preview_only");
        return proposal;
    }

    private boolean hardFactsComplete(CandidateItemDTO fact, PlanningStateDTO state) {
        HardConstraintsDTO hard = state.getConstraintState() == null
                ? null : state.getConstraintState().getHardConstraints();
        if (hard == null) {
            return true;
        }
        if ((!safeList(hard.getMustIncludeMajorIds()).isEmpty() || !safeList(hard.getMustExcludeMajorIds()).isEmpty())
                && (blank(fact.getMajorId()) || "0".equals(fact.getMajorId().trim()))) {
            return false;
        }
        if ((!safeList(hard.getMustIncludeRegionIds()).isEmpty() || !safeList(hard.getMustExcludeRegionIds()).isEmpty())
                && (blank(fact.getProvinceId()) || blank(fact.getCityId()))) {
            return false;
        }
        if ((!safeList(hard.getMustIncludeRegions()).isEmpty() || !safeList(hard.getMustExcludeRegions()).isEmpty())
                && (blank(fact.getProvinceName()) || blank(fact.getCityName()))) {
            return false;
        }
        if ((!safeList(hard.getMustIncludeMajors()).isEmpty() || !safeList(hard.getMustExcludeMajors()).isEmpty())
                && (blank(fact.getMajorName()) || blank(fact.getMajorDiscipline()) || blank(fact.getMajorCategory()))) {
            return false;
        }
        return safeList(hard.getMustIncludeSchools()).isEmpty() && safeList(hard.getMustExcludeSchools()).isEmpty();
    }

    private boolean blank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private String digest(Object value) {
        return EvaluationVersion.sha256(JSON.toJSONString(value, SerializerFeature.MapSortField,
                SerializerFeature.SortField, SerializerFeature.WriteMapNullValue));
    }

    private <Value> Value copy(Value value, Class<Value> type) {
        return JSON.parseObject(JSON.toJSONString(value), type);
    }

    private <Value> List<Value> safeList(List<Value> values) {
        return values == null ? new ArrayList<Value>() : values;
    }
}
