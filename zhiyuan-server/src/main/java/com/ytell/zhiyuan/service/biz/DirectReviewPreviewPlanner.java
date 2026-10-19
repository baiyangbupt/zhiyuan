package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.serializer.SerializerFeature;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FindingPostconditionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
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
    /** J5.5b：确认模式才把冻结方案提升为 ready；预览模式保持 preview_only 原样。 */
    private final boolean confirmable;

    DirectReviewPreviewPlanner() {
        this(false);
    }

    DirectReviewPreviewPlanner(boolean confirmable) {
        this.confirmable = confirmable;
    }

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
        if (!PriorityRuleSupport.confirmedRules(state).isEmpty()) {
            return blocked(proposal, "review_fix_direct_unsupported");
        }
        // 组模式（专业组/专业单元）与普通专业模式共用同一份冻结回放契约，
        // 但排序对象是 unit：只在 unit 分支内校验并冻结 units。
        boolean unitMode = "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel())
                || !safeList(state.getWorkingPlanState().getUnits()).isEmpty()
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty();
        return unitMode
                ? planUnits(proposal, state, candidates, finding, command, reevaluate)
                : planItems(proposal, state, candidates, finding, command, reevaluate);
    }

    private FixProposalDTO planItems(FixProposalDTO proposal, PlanningStateDTO state,
                                     List<CandidateItemDTO> candidates,
                                     EvaluationFindingDTO finding, PlanCommandDTO command,
                                     Function<PlanningStateDTO, ReviewStateDTO> reevaluate) {
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
        frozen.setFactsDigest(digestJson(frozen.getSelectedFacts()));
        proposal.setFrozenReviewPlan(frozen);
        proposal.setCanonicalObjectiveDigest(PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest());
        proposal.setPlanContentDigest(planContentDigest(state));
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
        // 摘要必须在“提升为 ready”之前算：previewDigest 是用户在只读预览里看到的那个值，
        // prepare 用确认模式重算时若把 dryRunResult.status 的差异算进去，合法的确认会被判 409。
        proposal.getDryRunResult().setStatus("preview_only");
        proposal.setProposalId("fp_" + digest(Arrays.asList(command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), command.getCommandDigest(), proposal.getActions())).substring(0, 16));
        proposal.setPreviewDigest(digest(Arrays.asList(proposal.getProposalId(), command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), proposal.getCanonicalObjectiveDigest(), frozen,
                proposal.getActions(), proposal.getDryRunResult(), postcondition)));
        if (confirmable) {
            // J5.5b：只有“冻结方案 + 原探针后置条件都成立”的提案才允许进入确认链。
            proposal.setStatus("ready");
            proposal.setRequiresConfirmation(true);
            proposal.setSourceVersionGuard(state.getVersion());
            command.setExecutable(true);
            proposal.getDryRunResult().setStatus("ready");
        } else {
            proposal.setBlockingReason("review_fix_prepare_unavailable");
            proposal.getBlockingReasonCodes().add("review_fix_prepare_unavailable");
        }
        return proposal;
    }

    /**
     * 组模式（专业单元）倒挂修复：排序对象从 volunteer 换成 unit，冻结与回放
     * 复用 CanonicalPlanningRuntime 的 unit 排序/扁平化逻辑，避免另写一套顺序推导。
     */
    private FixProposalDTO planUnits(FixProposalDTO proposal, PlanningStateDTO state,
                                     List<CandidateItemDTO> candidates,
                                     EvaluationFindingDTO finding, PlanCommandDTO command,
                                     Function<PlanningStateDTO, ReviewStateDTO> reevaluate) {
        List<DraftUnitDTO> selected = safeList(state.getWorkingPlanState().getUnits());
        List<OrderedUnitDTO> ordered = new ArrayList<OrderedUnitDTO>(
                safeList(state.getOrderedPlanState().getUnits()));
        if (ordered.isEmpty()
                || ordered.stream().anyMatch(unit -> unit == null || unit.getPosition() == null)
                || selected.stream().anyMatch(unit -> unit == null || Strings.isNullOrEmpty(unit.getUnitId()))) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        ordered.sort(Comparator.comparing(OrderedUnitDTO::getPosition));
        Set<String> selectedIds = new LinkedHashSet<String>();
        // 专业组会话的工作台可能只存 draft items、不存 working units；此时以
        // ordered units 作为当前选中集（与 review 的 group entry 口径一致）。
        if (selected.isEmpty()) {
            for (OrderedUnitDTO unit : ordered) {
                if (Strings.isNullOrEmpty(unit.getUnitId()) || !selectedIds.add(unit.getUnitId())) {
                    return blocked(proposal, "review_fix_selection_incomplete");
                }
            }
        } else {
            for (DraftUnitDTO unit : selected) {
                if (Boolean.TRUE.equals(unit.getLocked())) {
                    return blocked(proposal, "review_fix_order_locked");
                }
                if (!selectedIds.add(unit.getUnitId())) {
                    return blocked(proposal, "review_fix_selection_incomplete");
                }
            }
        }
        Map<String, OrderedUnitDTO> orderedById = new LinkedHashMap<String, OrderedUnitDTO>();
        Integer previousPosition = null;
        for (OrderedUnitDTO unit : ordered) {
            if (Boolean.TRUE.equals(unit.getLocked()) || Boolean.TRUE.equals(unit.getPinned())
                    || unit.getPinnedPosition() != null) {
                return blocked(proposal, "review_fix_order_locked");
            }
            // 线上 group 方案的位置可能稀疏（1,2,8,9...），只要严格递增且唯一即可；
            // 回放时 applyFrozenOrdering 会统一重排为 1..n。
            if (Strings.isNullOrEmpty(unit.getUnitId()) || unit.getPosition() == null
                    || (previousPosition != null && unit.getPosition() <= previousPosition)
                    || orderedById.put(unit.getUnitId(), unit) != null) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
            previousPosition = unit.getPosition();
        }
        if (!selectedIds.equals(orderedById.keySet())) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        Set<String> authorized = new LinkedHashSet<String>();
        if (command.getReorderTargets() == null || command.getReorderTargets().isEmpty()) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        for (EvaluationEntryRefDTO ref : command.getReorderTargets()) {
            if (ref == null || !"unit".equals(ref.getLevel()) || !selectedIds.contains(ref.getId())
                    || !authorized.add(ref.getId())) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
        }
        // 单元级录取率：单元行自带优先；缺失时退回学校投档比例。任一缺失/非有限即 fail closed。
        Map<String, Double> ratios = new LinkedHashMap<String, Double>();
        for (OrderedUnitDTO unit : ordered) {
            Double ratio = unit.getAdmissionRatio() != null
                    ? unit.getAdmissionRatio() : unit.getSchoolEnrollRatio();
            if (ratio == null || !Double.isFinite(ratio)) {
                return blocked(proposal, "review_fix_facts_incomplete");
            }
            ratios.put(unit.getUnitId(), ratio);
        }
        List<PlanOrderingEngine.OrderEntry> entries = new ArrayList<PlanOrderingEngine.OrderEntry>();
        for (OrderedUnitDTO unit : ordered) {
            entries.add(new PlanOrderingEngine.OrderEntry(unit.getUnitId(), unit.getTier(), false,
                    !authorized.contains(unit.getUnitId())));
        }
        PlanOrderingEngine.OrderResult result = PlanOrderingEngine.orderByProbability(entries, ratios);
        PlanningStateDTO after = copy(state, PlanningStateDTO.class);
        PlanSolverResultDTO frozenOrder = new PlanSolverResultDTO();
        frozenOrder.setSelectedEntityIds(new ArrayList<String>(result.orderedIds));
        frozenOrder.setOrderedEntityIds(new ArrayList<String>(result.orderedIds));
        frozenOrder.setStatus("ready");
        frozenOrder.setSolverVersion(StagedDeterministicPlanSolver.SOLVER_VERSION);
        frozenOrder.setInputDigest(digest(Arrays.asList(command.getEvaluationVersion(),
                command.getCommandDigest(), result.orderedIds)));
        try {
            CanonicalPlanningRuntime.applyFrozenOrdering(after, frozenOrder, true);
        } catch (RuntimeException invalid) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        List<CandidateItemDTO> unitFacts = factsForUnits(new ArrayList<String>(selectedIds),
                after.getOrderedPlanState().getUnits(), candidates);
        if (unitFacts == null) {
            return blocked(proposal, "review_fix_facts_incomplete");
        }
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
        for (CandidateItemDTO fact : unitFacts) {
            frozen.getSelectedFacts().add(copy(fact, CandidateItemDTO.class));
        }
        frozen.setFactsDigest(digestJson(frozen.getSelectedFacts()));
        proposal.setFrozenReviewPlan(frozen);
        proposal.setCanonicalObjectiveDigest(PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest());
        proposal.setPlanContentDigest(planContentDigest(state));
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("reorder_volunteers");
        action.setLevel("unit");
        action.setSourceCheckCode(finding.getCode());
        action.setUnitIds(new ArrayList<String>(result.orderedIds));
        proposal.getActions().add(action);
        proposal.getDryRunResult().setBeforeUnitTotal(selectedIds.size());
        proposal.getDryRunResult().setAfterUnitTotal(selectedIds.size());
        proposal.getDryRunResult().setBeforeUnitIds(new LinkedHashSet<String>(selectedIds));
        proposal.getDryRunResult().setAfterUnitIds(new LinkedHashSet<String>(selectedIds));
        proposal.getDryRunResult().setStatus("preview_only");
        proposal.setProposalId("fp_" + digest(Arrays.asList(command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), command.getCommandDigest(), proposal.getActions())).substring(0, 16));
        proposal.setPreviewDigest(digest(Arrays.asList(proposal.getProposalId(), command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), proposal.getCanonicalObjectiveDigest(), frozen,
                proposal.getActions(), proposal.getDryRunResult(), postcondition)));
        if (confirmable) {
            proposal.setStatus("ready");
            proposal.setRequiresConfirmation(true);
            proposal.setSourceVersionGuard(state.getVersion());
            command.setExecutable(true);
            proposal.getDryRunResult().setStatus("ready");
        } else {
            proposal.setBlockingReason("review_fix_prepare_unavailable");
            proposal.getBlockingReasonCodes().add("review_fix_prepare_unavailable");
        }
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
        return digestJson(value);
    }

    /** 与预览完全相同的序列化口径：apply 侧重算 planContentDigest / factsDigest 必须逐字一致。 */
    static String digestJson(Object value) {
        return EvaluationVersion.sha256(JSON.toJSONString(value, SerializerFeature.MapSortField,
                SerializerFeature.SortField, SerializerFeature.WriteMapNullValue));
    }

    /** 方案内容摘要（工作草案 + 排序态），prepare 冻结、apply 前比对漂移。 */
    static String planContentDigest(PlanningStateDTO state) {
        return digestJson(Arrays.asList(state.getWorkingPlanState(), state.getOrderedPlanState()));
    }

    /**
     * 按冻结的实体顺序从**当前** effective candidates 重建事实列表并计算与预览同口径的摘要。
     * 任一实体缺失、重复或候选重复出现返回 null（调用方按 facts_changed fail closed）。
     */
    static String factsDigestForEntities(List<String> entityIds, List<CandidateItemDTO> candidates) {
        if (entityIds == null || entityIds.isEmpty()) {
            return null;
        }
        Set<String> wanted = new LinkedHashSet<String>();
        for (String identity : entityIds) {
            if (Strings.isNullOrEmpty(identity) || !wanted.add(identity)) {
                return null;
            }
        }
        Map<String, CandidateItemDTO> factsById = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : candidates == null ? new ArrayList<CandidateItemDTO>() : candidates) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())
                    || !wanted.contains(candidate.getVolunteerId())) {
                continue;
            }
            if (factsById.put(candidate.getVolunteerId(), candidate) != null) {
                return null;
            }
        }
        List<CandidateItemDTO> facts = new ArrayList<CandidateItemDTO>();
        for (String identity : entityIds) {
            CandidateItemDTO fact = factsById.get(identity);
            if (fact == null) {
                return null;
            }
            facts.add(fact);
        }
        return digestJson(facts);
    }

    /**
     * 组模式事实摘要：按 unit 顺序、unit 内 major 顺序收集各专业志愿的候选事实，
     * 志愿身份去重后序列化。任一选中单元缺失/重复、事实缺失或候选重复出现返回 null。
     *
     * <p>apply 侧必须用 frozen.orderedPlan.units + frozen.selectedEntityIds 重算同一口径，
     * 因此单元顺序以冻结后的 ordered units 为准，selectedUnitIds 只做身份集合校验。</p>
     */
    static String factsDigestForUnits(List<String> selectedUnitIds, List<OrderedUnitDTO> orderedUnits,
                                      List<CandidateItemDTO> candidates) {
        List<CandidateItemDTO> facts = factsForUnits(selectedUnitIds, orderedUnits, candidates);
        return facts == null ? null : digestJson(facts);
    }

    /** 组模式事实列表（按 unit→major 顺序）；Search 组模式补齐切片共用同一口径。 */
    static List<CandidateItemDTO> factsForUnits(List<String> selectedUnitIds,
                                                        List<OrderedUnitDTO> orderedUnits,
                                                        List<CandidateItemDTO> candidates) {
        if (selectedUnitIds == null || selectedUnitIds.isEmpty()) {
            return null;
        }
        Set<String> wantedUnits = new LinkedHashSet<String>();
        for (String unitId : selectedUnitIds) {
            if (Strings.isNullOrEmpty(unitId) || !wantedUnits.add(unitId)) {
                return null;
            }
        }
        if (orderedUnits == null) {
            return null;
        }
        Set<String> seenUnits = new LinkedHashSet<String>();
        Set<String> wantedVolunteers = new LinkedHashSet<String>();
        for (OrderedUnitDTO unit : orderedUnits) {
            if (unit == null || Strings.isNullOrEmpty(unit.getUnitId())) {
                return null;
            }
            if (!wantedUnits.contains(unit.getUnitId())) {
                continue;
            }
            if (!seenUnits.add(unit.getUnitId())) {
                return null;
            }
            List<PlanningUnitMajorDTO> majors = unit.getMajorItems() == null
                    ? new ArrayList<PlanningUnitMajorDTO>() : unit.getMajorItems();
            for (PlanningUnitMajorDTO major : majors) {
                if (major == null || Strings.isNullOrEmpty(major.getVolunteerId())) {
                    return null;
                }
                wantedVolunteers.add(major.getVolunteerId());
            }
        }
        if (!seenUnits.equals(wantedUnits)) {
            return null;
        }
        Map<String, CandidateItemDTO> factsById = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : candidates == null ? new ArrayList<CandidateItemDTO>() : candidates) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())
                    || !wantedVolunteers.contains(candidate.getVolunteerId())) {
                continue;
            }
            if (factsById.put(candidate.getVolunteerId(), candidate) != null) {
                return null;
            }
        }
        List<CandidateItemDTO> facts = new ArrayList<CandidateItemDTO>();
        for (String volunteerId : wantedVolunteers) {
            CandidateItemDTO fact = factsById.get(volunteerId);
            if (fact == null) {
                return null;
            }
            facts.add(fact);
        }
        return facts;
    }

    private <Value> Value copy(Value value, Class<Value> type) {
        return JSON.parseObject(JSON.toJSONString(value), type);
    }

    private <Value> List<Value> safeList(List<Value> values) {
        return values == null ? new ArrayList<Value>() : values;
    }
}
