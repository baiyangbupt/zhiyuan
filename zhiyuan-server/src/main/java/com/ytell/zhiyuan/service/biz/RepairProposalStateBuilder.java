package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationPreviewDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateShortageDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

final class RepairProposalStateBuilder {

    private RepairProposalStateBuilder() {
    }

    static FixProposalStateDTO newState(PlanningStateDTO state, ReviewStateDTO reviewState) {
        FixProposalStateDTO proposalState = new FixProposalStateDTO();
        proposalState.setStatus(RepairProposalTaxonomy.Status.READY);
        proposalState.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposalState.setSourceVersion(state == null ? null : state.getVersion());
        proposalState.setSourceReviewVersion(reviewState == null ? null : reviewState.getSourceVersion());
        proposalState.setSourceVersionGuard(state == null ? null : state.getVersion());
        return proposalState;
    }

    static FixProposalStateDTO newUserGoalState(PlanningStateDTO state) {
        FixProposalStateDTO proposalState = new FixProposalStateDTO();
        proposalState.setStatus(RepairProposalTaxonomy.Status.EMPTY);
        proposalState.setProposalSource(RepairProposalTaxonomy.ProposalSource.USER_GOAL);
        proposalState.setSourceVersion(state == null ? null : state.getVersion());
        proposalState.setSourceVersionGuard(state == null ? null : state.getVersion());
        return proposalState;
    }

    static String resolveStateStatus(List<FixProposalDTO> proposals) {
        if (proposals == null || proposals.isEmpty()) {
            return RepairProposalTaxonomy.Status.EMPTY;
        }
        boolean hasReady = proposals.stream()
                .anyMatch(proposal -> proposal != null && RepairProposalTaxonomy.isReadyStatus(proposal.getStatus()));
        if (hasReady) {
            return RepairProposalTaxonomy.Status.READY;
        }
        boolean hasPreviewOnly = proposals.stream()
                .anyMatch(proposal -> proposal != null && RepairProposalTaxonomy.isPreviewOnlyStatus(proposal.getStatus()));
        if (hasPreviewOnly) {
            return RepairProposalTaxonomy.Status.PREVIEW_ONLY;
        }
        return RepairProposalTaxonomy.Status.BLOCKED_OR_INFO;
    }

    static Map<String, List<CompensationActionDTO>> groupCompensationActionsByCheck(CompensationPreviewDTO compensationPreview) {
        Map<String, List<CompensationActionDTO>> result = new LinkedHashMap<String, List<CompensationActionDTO>>();
        if (compensationPreview == null || compensationPreview.getActions() == null) {
            return result;
        }
        for (CompensationActionDTO action : compensationPreview.getActions()) {
            if (action == null || Strings.isNullOrEmpty(action.getSourceCheckCode())) {
                continue;
            }
            result.computeIfAbsent(action.getSourceCheckCode(), key -> Lists.newArrayList()).add(action);
        }
        return result;
    }

    static FixProposalDTO findProposal(FixProposalStateDTO proposalState, String proposalId) {
        if (proposalState == null || proposalState.getProposals() == null || Strings.isNullOrEmpty(proposalId)) {
            return null;
        }
        return proposalState.getProposals().stream()
                .filter(proposal -> proposalId.equals(proposal.getProposalId()))
                .findFirst()
                .orElse(null);
    }

    static FixProposalDTO buildBaseProposal(PlanningStateDTO state,
                                            ReviewCheckDTO check,
                                            List<CompensationActionDTO> compensationActions,
                                            Integer sourceReviewVersion) {
        return buildBaseProposal(state, check, compensationActions, sourceReviewVersion, null);
    }

    /**
     * J5.2：策略可由统一评价的 objectiveDelta 覆盖（ findings 是权威）；
     * override 为空时退回 check 自身解析，旧行为不变。
     */
    static FixProposalDTO buildBaseProposal(PlanningStateDTO state,
                                            ReviewCheckDTO check,
                                            List<CompensationActionDTO> compensationActions,
                                            Integer sourceReviewVersion,
                                            String strategyOverride) {
        if (check == null || Strings.isNullOrEmpty(check.getCode())) {
            return null;
        }
        String strategy = Strings.isNullOrEmpty(strategyOverride)
                ? resolveStrategy(check, compensationActions)
                : RepairProposalTaxonomy.normalizeStrategy(strategyOverride);
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId(buildProposalId(state, check, strategy));
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setSourceReviewVersion(sourceReviewVersion);
        proposal.setSourceVersionGuard(state == null ? null : state.getVersion());
        proposal.getSourceCheckCodes().add(check.getCode());
        proposal.setStrategy(strategy);
        proposal.setTitle(buildTitle(check, strategy));
        proposal.setRequiresConfirmation(Boolean.TRUE.equals(check.getRequiresConfirmation()));
        proposal.setAffectedUnitIds(defaultList(check.getAffectedUnitIds()));
        proposal.setAffectedVolunteerIds(defaultList(check.getAffectedVolunteerIds()));
        proposal.setSummary(buildSummary(check, strategy));
        if (RepairProposalTaxonomy.isCannotSatisfyStrategy(strategy)) {
            proposal.setBlockingReason(proposal.getSummary());
            addBlockingReasonCode(proposal, resolveBlockingReasonCode(check));
            proposal.setRequiresConfirmation(false);
        }
        proposal.setImpact(buildImpact(check, compensationActions));
        for (CompensationActionDTO action : defaultCompensationActions(compensationActions)) {
            proposal.getActions().add(toFixProposalAction(action));
        }
        return proposal;
    }

    static String resolveStrategy(ReviewCheckDTO check, List<CompensationActionDTO> compensationActions) {
        if (check == null) {
            return RepairProposalTaxonomy.Strategy.NO_OP;
        }
        if (compensationActions != null && !compensationActions.isEmpty()) {
            String actionType = compensationActions.get(0).getType();
            String strategy = RepairProposalTaxonomy.strategyForCompensationActionType(actionType);
            if (!Strings.isNullOrEmpty(strategy)) {
                return strategy;
            }
        }
        if ("item".equals(check.getScopeKind())) {
            if (!defaultList(check.getAffectedVolunteerIds()).isEmpty() || !defaultList(check.getAffectedUnitIds()).isEmpty()) {
                return Strings.isNullOrEmpty(check.getDefaultFixStrategy())
                        ? RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS
                        : RepairProposalTaxonomy.normalizeStrategy(check.getDefaultFixStrategy());
            }
            return RepairProposalTaxonomy.Strategy.CANNOT_SATISFY;
        }
        if ("informational".equals(check.getScopeKind())) {
            return RepairProposalTaxonomy.Strategy.NO_OP;
        }
        if ("ordering_risk".equals(check.getCategory())) {
            return RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY;
        }
        if ("major_group_inner".equals(check.getScopeKind())) {
            return Strings.isNullOrEmpty(check.getDefaultFixStrategy())
                    ? RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY
                    : RepairProposalTaxonomy.normalizeStrategy(check.getDefaultFixStrategy());
        }
        return RepairProposalTaxonomy.Strategy.CANNOT_SATISFY;
    }

    private static String buildProposalId(PlanningStateDTO state, ReviewCheckDTO check, String strategy) {
        String raw = String.join("|",
                String.valueOf(state == null ? null : state.getSessionId()),
                String.valueOf(state == null ? null : state.getVersion()),
                String.valueOf(check.getCode()),
                String.valueOf(strategy),
                String.join(",", defaultList(check.getAffectedUnitIds())),
                String.join(",", defaultList(check.getAffectedVolunteerIds())));
        return "fp_" + sha1Hex(raw).substring(0, 16);
    }

    private static String buildTitle(ReviewCheckDTO check, String strategy) {
        String label = Strings.isNullOrEmpty(check.getLabel()) ? check.getSummary() : check.getLabel();
        if (RepairProposalTaxonomy.isCannotSatisfyStrategy(strategy)) {
            return label + "暂时无法自动修复";
        }
        if (RepairProposalTaxonomy.isNoOpStrategy(strategy)) {
            return label + "仅需关注";
        }
        return "修复" + label;
    }

    private static String buildSummary(ReviewCheckDTO check, String strategy) {
        if (RepairProposalTaxonomy.isCannotSatisfyStrategy(strategy)) {
            return buildCannotSatisfySummary(check);
        }
        if (RepairProposalTaxonomy.isNoOpStrategy(strategy)) {
            return "该问题属于提醒或核验项，默认不自动调整方案。";
        }
        if (!Strings.isNullOrEmpty(check.getSuggestedAction())) {
            return check.getSuggestedAction();
        }
        return check.getSummary();
    }

    private static String buildCannotSatisfySummary(ReviewCheckDTO check) {
        String code = check == null ? null : check.getCode();
        if ("count_validation".equals(code)) {
            if ("count_over_limit".equals(check.getReasonCode())) {
                return "当前方案数量多于官方要求，需要先人工精简后再重新审查。";
            }
            return "当前候选不足，暂时无法补齐目标志愿数量。";
        }
        if ("safety_guard".equals(code) || "edge_score".equals(code)) {
            return "当前候选里缺少可用的保底志愿，暂时无法补强安全垫。";
        }
        if ("ratio_distribution".equals(code)) {
            return "当前候选里缺少目标冲稳保区间的可用志愿，暂时无法调整配比。";
        }
        if ("probability_gap".equals(code)) {
            return "当前候选里缺少断层区间的可用志愿，暂时无法补齐录取率梯度。";
        }
        if ("probability_inversion".equals(code)) {
            return "当前方案缺少可重排或可替换的有效志愿，暂时无法修复录取率倒挂。";
        }
        if ("group_inner_safety_guard".equals(code)
                || "major_group_safety_intent_alignment".equals(code)) {
            return "当前专业组内缺少可用的安全垫专业，暂时无法自动修复。";
        }
        if ("item".equals(check == null ? null : check.getScopeKind())) {
            return "当前风险缺少可定位的志愿明细或可替换候选，暂时无法自动修复。";
        }
        return "当前候选或方案条件不足，暂时不能形成可执行修复方案。";
    }

    static void markBlocked(FixProposalDTO proposal, String reason, String reasonCode) {
        if (proposal == null) {
            return;
        }
        proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.setBlockingReason(reason);
        proposal.setRequiresConfirmation(false);
        addBlockingReasonCode(proposal, reasonCode);
    }

    static void addBlockingReasonCode(FixProposalDTO proposal, String reasonCode) {
        if (proposal == null || Strings.isNullOrEmpty(reasonCode)) {
            return;
        }
        if (proposal.getBlockingReasonCodes() == null) {
            proposal.setBlockingReasonCodes(Lists.newArrayList());
        }
        if (!proposal.getBlockingReasonCodes().contains(reasonCode)) {
            proposal.getBlockingReasonCodes().add(reasonCode);
        }
    }

    static void populateCandidateShortages(PlanningStateDTO state,
                                           ReviewCheckDTO check,
                                           FixProposalDTO proposal) {
        if (proposal == null) {
            return;
        }
        if (proposal.getCandidateShortages() == null) {
            proposal.setCandidateShortages(Lists.newArrayList());
        } else {
            proposal.getCandidateShortages().clear();
        }
        for (String reasonCode : defaultList(proposal.getBlockingReasonCodes())) {
            CandidateShortageDTO shortage = buildCandidateShortage(state, check, proposal, reasonCode);
            if (shortage != null) {
                proposal.getCandidateShortages().add(shortage);
            }
        }
    }

    static void suppressInvalidBlockedActionPreview(FixProposalDTO proposal) {
        if (proposal == null || !RepairProposalTaxonomy.isBlockedStatus(proposal.getStatus())) {
            return;
        }
        if (!defaultList(proposal.getBlockingReasonCodes()).contains("objective_validation_not_improved")) {
            return;
        }
        proposal.getActions().clear();
    }

    private static CandidateShortageDTO buildCandidateShortage(PlanningStateDTO state,
                                                               ReviewCheckDTO check,
                                                               FixProposalDTO proposal,
                                                               String reasonCode) {
        if (Strings.isNullOrEmpty(reasonCode)) {
            return null;
        }
        CandidateShortageDTO shortage = new CandidateShortageDTO();
        shortage.setStrategy(proposal.getStrategy());
        shortage.setSourceCheckCode(check == null ? null : check.getCode());
        shortage.setReasonCode(reasonCode);
        shortage.setScope(resolveShortageScope(reasonCode));
        shortage.setMessage(buildShortageMessage(proposal, reasonCode, shortage.getScope()));
        applyShortageCounts(state, check, proposal, reasonCode, shortage);
        return shortage;
    }

    private static String resolveShortageScope(String reasonCode) {
        if ("replacement_pair_missing".equals(reasonCode)
                || "no_sort_or_replacement_candidate".equals(reasonCode)) {
            return "capacity_or_replacement";
        }
        if ("objective_validation_not_improved".equals(reasonCode)) {
            return "objective_validation";
        }
        if ("count_over_limit".equals(reasonCode)) {
            return "current_plan";
        }
        if ("volunteer_model_mismatch".equals(reasonCode)
                || "risk_unit_unresolved".equals(reasonCode)
                || "risk_item_unresolved".equals(reasonCode)
                || "candidate_or_plan_condition_insufficient".equals(reasonCode)) {
            return "unknown";
        }
        return "candidate_pool";
    }

    private static String buildShortageMessage(FixProposalDTO proposal, String reasonCode, String scope) {
        if ("capacity_or_replacement".equals(scope)) {
            return "当前不是单纯缺候选，而是方案已满或缺少完整一进一出的替换配对。";
        }
        if ("objective_validation".equals(scope)) {
            return Strings.isNullOrEmpty(proposal.getBlockingReason())
                    ? "已有预览没有让本次审查目标变好，因此不能作为修复结果。"
                    : proposal.getBlockingReason();
        }
        if ("hard_constraints".equals(scope)) {
            return "候选池里有可用于这个目标的候选，但按已确认的报考条件过滤后数量不足。";
        }
        if ("tier_candidate_insufficient".equals(reasonCode)) {
            return "当前可用于规划的候选池里，目标冲稳保区间候选不足。";
        }
        if ("probability_gap_candidate_insufficient".equals(reasonCode)) {
            return "当前可用于规划的候选池里，断层中间录取率候选不足。";
        }
        if ("safety_candidate_insufficient".equals(reasonCode)) {
            return "当前可用于规划的候选池里，可用保底或安全垫候选不足。";
        }
        if ("count_over_limit".equals(reasonCode)) {
            return "当前方案数量多于官方要求，需要先精简再重新审查。";
        }
        if ("major_group_safety_candidate_insufficient".equals(reasonCode)
                || "partial_major_group_safety_candidate_missing".equals(reasonCode)) {
            return "当前可用于规划的候选池里，部分专业组缺少可补入的组内安全垫专业。";
        }
        if ("safe_replacement_candidate_insufficient".equals(reasonCode)
                || "risk_item_unresolved_or_replacement_missing".equals(reasonCode)) {
            return "当前可用于规划的候选池里，缺少同层次、风险更低、专业相近且院校层次代价可接受的替换候选。";
        }
        if (!Strings.isNullOrEmpty(proposal.getBlockingReason())) {
            return proposal.getBlockingReason();
        }
        return "当前可用于规划的候选池或方案条件不足，暂时不能形成可执行修复方案。";
    }

    private static void applyShortageCounts(PlanningStateDTO state,
                                            ReviewCheckDTO check,
                                            FixProposalDTO proposal,
                                            String reasonCode,
                                            CandidateShortageDTO shortage) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        if (candidatePoolState == null) {
            return;
        }
        boolean majorGroupMode = isMajorGroupMode(candidatePoolState);
        if ("candidate_pool_insufficient".equals(reasonCode)) {
            int required = positiveCount(candidatePoolState.getRequiredCount());
            int current = majorGroupMode ? currentPlanUnitCount(state) : currentPlanVolunteerCount(state);
            int shortageCount = required > current ? required - current : 0;
            int availableCount = countAvailableCandidates(state, null, majorGroupMode, true);
            shortage.setRequiredCount(required > 0 ? required : null);
            shortage.setCurrentCount(current);
            shortage.setShortageCount(shortageCount > 0 ? shortageCount : null);
            shortage.setAvailableCount(availableCount);
            applyHardConstraintAttribution(state, proposal, reasonCode, shortage, shortageCount,
                    countAvailableCandidates(state, null, majorGroupMode, true, false),
                    countAvailableCandidates(state, null, majorGroupMode, false, false));
            return;
        }
        if ("count_over_limit".equals(reasonCode)) {
            int required = positiveCount(candidatePoolState.getRequiredCount());
            int current = majorGroupMode ? currentPlanUnitCount(state) : currentPlanVolunteerCount(state);
            shortage.setRequiredCount(required > 0 ? required : null);
            shortage.setCurrentCount(current);
            shortage.setShortageCount(null);
            shortage.setAvailableCount(null);
            return;
        }
        if ("tier_candidate_insufficient".equals(reasonCode)
                || "safety_candidate_insufficient".equals(reasonCode)) {
            String tier = "safety_candidate_insufficient".equals(reasonCode)
                    ? "保" : resolveShortageTier(state, check, majorGroupMode);
            shortage.setTargetTier(tier);
            int required = positiveCount(candidatePoolState.getRequiredTierCounts() == null
                    ? null : candidatePoolState.getRequiredTierCounts().get(tier));
            int current = Strings.isNullOrEmpty(tier)
                    ? 0
                    : (majorGroupMode ? currentPlanUnitTierCount(state, tier) : currentPlanVolunteerTierCount(state, tier));
            int shortageCount = required > current ? required - current : 0;
            int availableCount = countAvailableCandidates(state, tier, majorGroupMode, true);
            shortage.setRequiredCount(required > 0 ? required : null);
            shortage.setCurrentCount(Strings.isNullOrEmpty(tier) ? null : current);
            shortage.setShortageCount(shortageCount > 0 ? shortageCount : null);
            shortage.setAvailableCount(availableCount);
            applyHardConstraintAttribution(state, proposal, reasonCode, shortage, shortageCount,
                    countAvailableCandidates(state, tier, majorGroupMode, true, false),
                    countAvailableCandidates(state, tier, majorGroupMode, false, false));
            return;
        }
        if ("probability_gap_candidate_insufficient".equals(reasonCode)) {
            int availableCount = countAvailableProbabilityGapCandidates(state, check, majorGroupMode, true);
            shortage.setRequiredCount(1);
            shortage.setAvailableCount(availableCount);
            applyHardConstraintAttribution(state, proposal, reasonCode, shortage, 1,
                    availableCount, countAvailableProbabilityGapCandidates(state, check, majorGroupMode, false));
            return;
        }
        if ("major_group_safety_candidate_insufficient".equals(reasonCode)
                || "partial_major_group_safety_candidate_missing".equals(reasonCode)) {
            int targetCount = defaultList(check == null ? null : check.getAffectedUnitIds()).size();
            int actionCount = countProposalActions(proposal, RepairProposalTaxonomy.ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY);
            shortage.setRequiredCount(targetCount > 0 ? targetCount : null);
            shortage.setCurrentCount(actionCount);
            shortage.setShortageCount(targetCount > actionCount ? targetCount - actionCount : null);
            shortage.setAvailableCount(actionCount);
            return;
        }
        if ("safe_replacement_candidate_insufficient".equals(reasonCode)
                || "risk_item_unresolved_or_replacement_missing".equals(reasonCode)) {
            int required = defaultList(check == null ? null : check.getAffectedVolunteerIds()).size();
            int actionCount = countReplacementPairs(proposal);
            shortage.setRequiredCount(required > 0 ? required : null);
            shortage.setCurrentCount(actionCount);
            shortage.setShortageCount(required > actionCount ? required - actionCount : null);
            shortage.setAvailableCount(actionCount);
        }
    }

    private static void applyHardConstraintAttribution(PlanningStateDTO state,
                                                       FixProposalDTO proposal,
                                                       String reasonCode,
                                                       CandidateShortageDTO shortage,
                                                       int requiredAvailableCount,
                                                       int availableWithHardConstraints,
                                                       int availableWithoutHardConstraints) {
        if (shortage == null
                || requiredAvailableCount <= 0
                || !RepairCandidateEligibility.hasConfirmedHardConstraints(state)
                || availableWithHardConstraints >= requiredAvailableCount
                || availableWithoutHardConstraints <= availableWithHardConstraints) {
            return;
        }
        shortage.setScope("hard_constraints");
        shortage.setMessage(buildShortageMessage(proposal, reasonCode, "hard_constraints"));
    }

    static String resolveBlockingReasonCode(ReviewCheckDTO check) {
        String code = check == null ? null : check.getCode();
        if ("count_validation".equals(code)) {
            if ("count_over_limit".equals(check.getReasonCode())) {
                return "count_over_limit";
            }
            return "candidate_pool_insufficient";
        }
        if ("safety_guard".equals(code) || "edge_score".equals(code)) {
            return "safety_candidate_insufficient";
        }
        if ("ratio_distribution".equals(code)) {
            return "tier_candidate_insufficient";
        }
        if ("probability_gap".equals(code)) {
            return "probability_gap_candidate_insufficient";
        }
        if ("probability_inversion".equals(code)) {
            return "no_sort_or_replacement_candidate";
        }
        if ("group_inner_safety_guard".equals(code)
                || "major_group_safety_intent_alignment".equals(code)) {
            return "major_group_safety_candidate_insufficient";
        }
        if ("item".equals(check == null ? null : check.getScopeKind())) {
            return "risk_item_unresolved_or_replacement_missing";
        }
        return "candidate_or_plan_condition_insufficient";
    }

    private static String buildImpact(ReviewCheckDTO check, List<CompensationActionDTO> compensationActions) {
        int affectedUnitCount = defaultList(check.getAffectedUnitIds()).size();
        int affectedVolunteerCount = defaultList(check.getAffectedVolunteerIds()).size();
        int actionCount = compensationActions == null ? 0 : compensationActions.size();
        if (actionCount > 0) {
            return String.format("预计新增或补充 %d 组动作；当前问题涉及 %d 个专业组、%d 条志愿。",
                    actionCount, affectedUnitCount, affectedVolunteerCount);
        }
        return String.format("当前问题涉及 %d 个专业组、%d 条志愿。", affectedUnitCount, affectedVolunteerCount);
    }

    private static FixProposalActionDTO toFixProposalAction(CompensationActionDTO action) {
        FixProposalActionDTO target = new FixProposalActionDTO();
        target.setActionType(action.getType());
        target.setLevel(action.getLevel());
        target.setSourceCheckCode(action.getSourceCheckCode());
        target.setSummary(action.getSummary());
        target.setDetail(action.getDetail());
        target.setUnitIds(defaultList(action.getUnitIds()));
        target.setVolunteerIds(defaultList(action.getVolunteerIds()));
        populateActionTotals(target);
        return target;
    }

    static void populateActionTotals(FixProposalDTO proposal) {
        if (proposal == null || proposal.getActions() == null) {
            return;
        }
        proposal.getActions().forEach(RepairProposalStateBuilder::populateActionTotals);
    }

    private static void populateActionTotals(FixProposalActionDTO action) {
        if (action == null) {
            return;
        }
        action.setTotalUnitCount(Math.max(defaultList(action.getRemoveUnitIds()).size(),
                Math.max(defaultList(action.getCandidateUnitIds()).size(), defaultList(action.getUnitIds()).size())));
        action.setTotalVolunteerCount(Math.max(defaultList(action.getRemoveVolunteerIds()).size(),
                Math.max(defaultList(action.getCandidateVolunteerIds()).size(), defaultList(action.getVolunteerIds()).size())));
        action.setTotalReplacementPairCount(defaultList(action.getReplacementPairs()).size());
    }

    private static String sha1Hex(String value) {
        String normalized = String.valueOf(value);
        try {
            MessageDigest messageDigest = MessageDigest.getInstance("SHA-1");
            byte[] digest = messageDigest.digest(normalized.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder();
            for (byte item : digest) {
                builder.append(String.format("%02x", item));
            }
            return builder.toString();
        } catch (Exception ex) {
            return UUID.nameUUIDFromBytes(normalized.getBytes(StandardCharsets.UTF_8)).toString().replace("-", "");
        }
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<CompensationActionDTO> defaultCompensationActions(List<CompensationActionDTO> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static int positiveCount(Integer value) {
        return value == null || value <= 0 ? 0 : value;
    }

    private static int currentPlanVolunteerCount(PlanningStateDTO state) {
        List<OrderedItemDTO> orderedItems = defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems());
        if (!orderedItems.isEmpty()) {
            return orderedItems.size();
        }
        return defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).size();
    }

    private static int currentPlanUnitCount(PlanningStateDTO state) {
        List<OrderedUnitDTO> orderedUnits = defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits());
        if (!orderedUnits.isEmpty()) {
            return orderedUnits.size();
        }
        List<DraftUnitDTO> draftUnits = defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getUnits());
        if (!draftUnits.isEmpty()) {
            return draftUnits.size();
        }
        return selectedUnitIds(state).size();
    }

    private static int currentPlanVolunteerTierCount(PlanningStateDTO state, String tier) {
        if (Strings.isNullOrEmpty(tier)) {
            return 0;
        }
        List<OrderedItemDTO> orderedItems = defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems());
        if (!orderedItems.isEmpty()) {
            return (int) orderedItems.stream().filter(item -> item != null && tier.equals(item.getTier())).count();
        }
        return (int) defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .filter(item -> item != null && tier.equals(item.getTier()))
                .count();
    }

    private static int currentPlanUnitTierCount(PlanningStateDTO state, String tier) {
        if (Strings.isNullOrEmpty(tier)) {
            return 0;
        }
        List<OrderedUnitDTO> orderedUnits = defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits());
        if (!orderedUnits.isEmpty()) {
            return (int) orderedUnits.stream().filter(unit -> unit != null && tier.equals(unit.getTier())).count();
        }
        List<DraftUnitDTO> draftUnits = defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getUnits());
        if (!draftUnits.isEmpty()) {
            return (int) draftUnits.stream().filter(unit -> unit != null && tier.equals(unit.getTier())).count();
        }
        List<CandidateItemDTO> candidates = defaultList(state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getItems());
        return (int) defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .map(item -> RepairCandidateSelector.findCandidate(candidates, item.getVolunteerId()))
                .filter(candidate -> candidate != null && tier.equals(candidate.getTier()))
                .map(RepairCandidateSelector::resolveInitialRecommendationUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .count();
    }

    private static String resolveShortageTier(PlanningStateDTO state, ReviewCheckDTO check, boolean majorGroupMode) {
        String tierByReason = resolveRatioTargetTier(check == null ? null : check.getReasonCode());
        if (!Strings.isNullOrEmpty(tierByReason)) {
            return tierByReason;
        }
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        if (candidatePoolState == null || candidatePoolState.getRequiredTierCounts() == null) {
            return null;
        }
        String shortageTier = null;
        int maxDeficit = 0;
        for (String tier : Lists.newArrayList("保", "稳", "冲")) {
            int required = positiveCount(candidatePoolState.getRequiredTierCounts().get(tier));
            int current = majorGroupMode ? currentPlanUnitTierCount(state, tier) : currentPlanVolunteerTierCount(state, tier);
            int deficit = required - current;
            if (deficit > maxDeficit) {
                maxDeficit = deficit;
                shortageTier = tier;
            }
        }
        if (Strings.isNullOrEmpty(shortageTier)) {
            return resolveRatioFallbackTier(state, majorGroupMode);
        }
        return shortageTier;
    }

    private static String resolveRatioFallbackTier(PlanningStateDTO state, boolean majorGroupMode) {
        int sprintCount = majorGroupMode ? currentPlanUnitTierCount(state, "冲") : currentPlanVolunteerTierCount(state, "冲");
        int safeCount = majorGroupMode ? currentPlanUnitTierCount(state, "稳") : currentPlanVolunteerTierCount(state, "稳");
        int protectCount = majorGroupMode ? currentPlanUnitTierCount(state, "保") : currentPlanVolunteerTierCount(state, "保");
        if (sprintCount > safeCount || sprintCount > protectCount) {
            return protectCount <= safeCount ? "保" : "稳";
        }
        return "保";
    }

    private static String resolveRatioTargetTier(String reasonCode) {
        if ("protect_tier_missing".equals(reasonCode) || "sprint_tier_over_limit".equals(reasonCode)) {
            return "保";
        }
        if ("sprint_tier_missing".equals(reasonCode)) {
            return "冲";
        }
        if ("tier_quota_mismatch".equals(reasonCode)) {
            return "保";
        }
        return null;
    }

    private static int countAvailableCandidates(PlanningStateDTO state,
                                                String tier,
                                                boolean majorGroupMode,
                                                boolean applyHardConstraints) {
        return countAvailableCandidates(state, tier, majorGroupMode, applyHardConstraints, true);
    }

    private static int countAvailableCandidates(PlanningStateDTO state,
                                                String tier,
                                                boolean majorGroupMode,
                                                boolean applyHardConstraints,
                                                boolean requireSafeCandidate) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        if (candidatePoolState == null) {
            return 0;
        }
        List<CandidateItemDTO> candidates = defaultList(candidatePoolState.getItems());
        Set<String> selectedVolunteerIds = selectedVolunteerIds(state);
        Set<String> selectedUnitIds = selectedUnitIds(state);
        if (majorGroupMode) {
            return (int) candidates.stream()
                    .filter(candidate -> availableCandidate(candidate, tier, selectedVolunteerIds, state,
                            applyHardConstraints, requireSafeCandidate))
                    .map(RepairCandidateSelector::resolveInitialRecommendationUnitId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .filter(unitId -> !selectedUnitIds.contains(unitId))
                    .distinct()
                    .count();
        }
        return (int) candidates.stream()
                .filter(candidate -> availableCandidate(candidate, tier, selectedVolunteerIds, state,
                        applyHardConstraints, requireSafeCandidate))
                .count();
    }

    private static boolean availableCandidate(CandidateItemDTO candidate,
                                              String tier,
                                              Set<String> selectedVolunteerIds,
                                              PlanningStateDTO state,
                                              boolean applyHardConstraints) {
        return availableCandidate(candidate, tier, selectedVolunteerIds, state, applyHardConstraints, true);
    }

    private static boolean availableCandidate(CandidateItemDTO candidate,
                                              String tier,
                                              Set<String> selectedVolunteerIds,
                                              PlanningStateDTO state,
                                              boolean applyHardConstraints,
                                              boolean requireSafeCandidate) {
        if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
            return false;
        }
        if (!Strings.isNullOrEmpty(tier) && !tier.equals(candidate.getTier())) {
            return false;
        }
        if (selectedVolunteerIds.contains(candidate.getVolunteerId())) {
            return false;
        }
        return (!requireSafeCandidate || RepairCandidateSelector.isCompensationSafeCandidate(candidate))
                && (!applyHardConstraints
                || RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state));
    }

    private static int countAvailableProbabilityGapCandidates(PlanningStateDTO state,
                                                              ReviewCheckDTO check,
                                                              boolean majorGroupMode,
                                                              boolean applyHardConstraints) {
        List<CandidateItemDTO> candidates = defaultList(state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getItems());
        List<Double> affectedRatios = affectedAdmissionRatios(state, check, candidates, majorGroupMode);
        if (affectedRatios.size() < 2) {
            return 0;
        }
        double min = affectedRatios.stream().min(Double::compareTo).orElse(0D);
        double max = affectedRatios.stream().max(Double::compareTo).orElse(0D);
        Set<String> selectedVolunteerIds = selectedVolunteerIds(state);
        Set<String> selectedUnitIds = selectedUnitIds(state);
        if (majorGroupMode) {
            return (int) candidates.stream()
                    .filter(candidate -> availableCandidate(candidate, null, selectedVolunteerIds, state, applyHardConstraints))
                    .filter(candidate -> candidate.getAdmissionRatio() != null
                            && candidate.getAdmissionRatio() > min
                            && candidate.getAdmissionRatio() < max)
                    .map(RepairCandidateSelector::resolveInitialRecommendationUnitId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .filter(unitId -> !selectedUnitIds.contains(unitId))
                    .distinct()
                    .count();
        }
        return (int) candidates.stream()
                .filter(candidate -> availableCandidate(candidate, null, selectedVolunteerIds, state, applyHardConstraints))
                .filter(candidate -> candidate.getAdmissionRatio() != null
                        && candidate.getAdmissionRatio() > min
                        && candidate.getAdmissionRatio() < max)
                .count();
    }

    private static List<Double> affectedAdmissionRatios(PlanningStateDTO state,
                                                        ReviewCheckDTO check,
                                                        List<CandidateItemDTO> candidates,
                                                        boolean majorGroupMode) {
        if (majorGroupMode) {
            Set<String> affectedUnitIds = new LinkedHashSet<String>(defaultList(check == null ? null : check.getAffectedUnitIds()));
            return defaultList(state == null || state.getOrderedPlanState() == null
                    ? null : state.getOrderedPlanState().getUnits()).stream()
                    .filter(unit -> unit != null && affectedUnitIds.contains(unit.getUnitId()))
                    .map(OrderedUnitDTO::getAdmissionRatio)
                    .filter(value -> value != null)
                    .collect(Collectors.toList());
        }
        return defaultList(check == null ? null : check.getAffectedVolunteerIds()).stream()
                .map(volunteerId -> RepairCandidateSelector.findCandidate(candidates, volunteerId))
                .filter(candidate -> candidate != null && candidate.getAdmissionRatio() != null)
                .map(CandidateItemDTO::getAdmissionRatio)
                .collect(Collectors.toList());
    }

    private static int countProposalActions(FixProposalDTO proposal, String actionType) {
        return (int) defaultList(proposal == null ? null : proposal.getActions()).stream()
                .filter(action -> action != null && actionType.equals(action.getActionType()))
                .count();
    }

    private static int countReplacementPairs(FixProposalDTO proposal) {
        return defaultList(proposal == null ? null : proposal.getActions()).stream()
                .filter(action -> action != null
                        && RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(action.getActionType()))
                .mapToInt(action -> defaultList(action.getReplacementPairs()).size())
                .sum();
    }

    private static Set<String> selectedVolunteerIds(PlanningStateDTO state) {
        Set<String> result = new LinkedHashSet<String>();
        defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).stream()
                .map(OrderedItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .forEach(result::add);
        defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .forEach(result::add);
        return result;
    }

    private static Set<String> selectedUnitIds(PlanningStateDTO state) {
        Set<String> result = new LinkedHashSet<String>();
        defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits()).stream()
                .map(OrderedUnitDTO::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .forEach(result::add);
        defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getUnits()).stream()
                .map(DraftUnitDTO::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .forEach(result::add);
        List<CandidateItemDTO> candidates = defaultList(state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getItems());
        defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).stream()
                .map(item -> RepairCandidateSelector.resolveUnitId(item.getVolunteerId(), candidates))
                .filter(value -> !Strings.isNullOrEmpty(value))
                .forEach(result::add);
        defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .map(item -> RepairCandidateSelector.resolveUnitId(item.getVolunteerId(), candidates))
                .filter(value -> !Strings.isNullOrEmpty(value))
                .forEach(result::add);
        return result;
    }
}
