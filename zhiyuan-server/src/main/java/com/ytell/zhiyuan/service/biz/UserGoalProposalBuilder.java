package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
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
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

import java.nio.charset.StandardCharsets;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

final class UserGoalProposalBuilder {

    private static final String REASON_ENGINE_NOT_READY = "user_goal_proposal_engine_not_ready";
    private static final String REASON_SOURCE_VERSION_MISMATCH = "source_version_mismatch";
    private static final String REASON_GOAL_UNCLEAR = "user_goal_unclear";
    private static final String REASON_TARGET_NOT_FOUND = "user_goal_target_not_found";
    private static final String REASON_ENTITY_NEEDS_CLARIFICATION = "user_goal_entity_needs_clarification";
    private UserGoalProposalBuilder() {
    }

    static FixProposalStateDTO build(PlanningStateDTO state, UserGoalFixProposalReq req) {
        FixProposalStateDTO proposalState = RepairProposalStateBuilder.newUserGoalState(state);
        FixProposalDTO proposal = buildProposal(state, req);
        proposalState.getProposals().add(proposal);
        proposalState.setTotal(proposalState.getProposals().size());
        proposalState.setStatus(RepairProposalStateBuilder.resolveStateStatus(proposalState.getProposals()));
        return proposalState;
    }

    private static FixProposalDTO buildProposal(PlanningStateDTO state, UserGoalFixProposalReq req) {
        String goalType = normalizeGoalType(req == null ? null : req.getGoalType());
        String guardReason = resolveGuardReasonCode(state, req, goalType);
        if (!Strings.isNullOrEmpty(guardReason)) {
            return buildBlockedProposal(state, req, goalType, guardReason);
        }
        if (RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE.equals(goalType)
                || RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE.equals(goalType)
                || RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE.equals(goalType)) {
            return buildScopeProposal(state, req, goalType);
        }
        if (RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE.equals(goalType)) {
            return buildTuitionBudgetProposal(state, req);
        }
        return buildBlockedProposal(state, req, goalType, REASON_ENGINE_NOT_READY);
    }

    private static FixProposalDTO buildBlockedProposal(PlanningStateDTO state,
                                                       UserGoalFixProposalReq req,
                                                       String goalType,
                                                       String reasonCode) {
        String message = buildMessage(goalType, reasonCode);

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId(buildProposalId(state, req, reasonCode));
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.USER_GOAL);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setSourceVersionGuard(state == null ? null : state.getVersion());
        proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.setStrategy(RepairProposalTaxonomy.Strategy.CANNOT_SATISFY);
        proposal.setTitle(buildTitle(goalType));
        proposal.setSummary(message);
        proposal.setBlockingReason(message);
        proposal.setRequiresConfirmation(false);
        proposal.getBlockingReasonCodes().add(reasonCode);
        proposal.getCandidateShortages().add(buildBoundaryShortage(reasonCode, message));
        proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.getDryRunResult().setMessage(message);
        if (REASON_ENGINE_NOT_READY.equals(reasonCode)) {
            proposal.getDryRunResult().getWarnings().add("当前只建立了复合目标提案协议，还没有生成可执行的方案调整动作。");
        }
        return proposal;
    }

    private static String resolveGuardReasonCode(PlanningStateDTO state, UserGoalFixProposalReq req, String goalType) {
        Integer guard = req == null ? null : req.getSourceVersionGuard();
        if (guard != null && state != null && state.getVersion() != null && !guard.equals(state.getVersion())) {
            return REASON_SOURCE_VERSION_MISMATCH;
        }
        if (Strings.isNullOrEmpty(goalType)) {
            return REASON_GOAL_UNCLEAR;
        }
        return null;
    }

    private static FixProposalDTO buildScopeProposal(PlanningStateDTO state,
                                                     UserGoalFixProposalReq req,
                                                     String goalType) {
        List<ScopeMatcher> scopes = buildScopeMatchers(scopesForGoal(req, goalType));
        if (scopes.isEmpty()) {
            return buildBlockedProposal(state, req, goalType, REASON_GOAL_UNCLEAR);
        }
        ScopeMatcher ambiguousScope = scopes.stream()
                .filter(ScopeMatcher::needsClarification)
                .findFirst()
                .orElse(null);
        if (ambiguousScope != null) {
            return buildScopeBlockedProposal(state, req, goalType, REASON_ENTITY_NEEDS_CLARIFICATION,
                    "“" + ambiguousScope.getValue() + "”还没有对应到明确范围，需要先确认后再生成调整预览。");
        }

        List<CandidateItemDTO> candidates = candidates(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, candidates);
        Set<String> selectedVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> selectedUnitIds = current.stream()
                .map(PlanVolunteer::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        String scopeLabel = scopeLabel(scopes);
        List<PlanVolunteer> currentMatches = current.stream()
                .filter(item -> matchesAny(item, scopes))
                .collect(Collectors.toList());
        List<CandidateItemDTO> candidateMatches = candidates.stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> matchesAny(candidate, scopes))
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .sorted(buildCandidatePreviewComparator())
                .collect(Collectors.toList());
        List<CandidateItemDTO> candidateNonMatches = candidates.stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> !matchesAny(candidate, scopes))
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .sorted(buildCandidatePreviewComparator())
                .collect(Collectors.toList());

        if (RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE.equals(goalType)) {
            return buildOnlyKeepProposal(state, req, scopeLabel, scopes, current, currentMatches, candidateMatches, selectedUnitIds);
        }
        if (RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE.equals(goalType)) {
            return buildMustIncludeProposal(state, req, scopeLabel, current, currentMatches, candidateMatches, selectedUnitIds);
        }
        return buildExcludeProposal(state, req, scopeLabel, current, currentMatches, candidateNonMatches, selectedUnitIds);
    }

    private static FixProposalDTO buildOnlyKeepProposal(PlanningStateDTO state,
                                                        UserGoalFixProposalReq req,
                                                        String scopeLabel,
                                                        List<ScopeMatcher> scopes,
                                                        List<PlanVolunteer> current,
                                                        List<PlanVolunteer> currentMatches,
                                                        List<CandidateItemDTO> candidateMatches,
                                                        Set<String> selectedUnitIds) {
        if (currentMatches.isEmpty() && candidateMatches.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE,
                    REASON_TARGET_NOT_FOUND, "当前方案和候选池里暂时都没有找到“" + scopeLabel + "”相关选择，不能直接生成只保留这个方向的调整预览。");
        }
        List<PlanVolunteer> removable = current.stream()
                .filter(item -> !matchesAny(item, scopes))
                .filter(item -> !item.isLocked())
                .collect(Collectors.toList());
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE,
                "只保留“" + scopeLabel + "”的调整预览");
        if (removable.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案已经都在“" + scopeLabel + "”范围内，本轮不需要为了这个目标调整方案。");
            proposal.setImpact("如果还想继续提高这个方向的质量，可以再要求我按院校层次、录取率或地域偏好做进一步优化。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案已经符合这个保留方向。");
            return proposal;
        }
        boolean majorGroupMode = isMajorGroupMode(state);
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                removable, candidateMatches, selectedUnitIds, majorGroupMode,
                Math.min(removable.size(), candidateMatches.size()),
                RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE);
        List<PlanVolunteer> remainingRemovable = remainingSources(removable, pairs);
        proposal.setSummary("当前方案中有 " + currentMatches.size() + " 条符合“" + scopeLabel + "”；如果只保留这个方向，另有 "
                + removable.size() + " 条需要处理。本次能替换 " + pairs.size() + " 条。");
        proposal.setImpact(remainingRemovable.isEmpty()
                ? "确认前不会改动当前方案；确认后会按这次预览处理，并同步刷新方案。"
                : "还有 " + remainingRemovable.size() + " 条暂时没有合适补位；本次会处理能替换或移出的部分，剩余部分需要放宽条件或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用保留范围内的候选替换其他志愿", pairs, majorGroupMode));
        }
        if (!remainingRemovable.isEmpty()) {
            proposal.getActions().add(removeAction("不在保留范围内且暂未找到补位的志愿", remainingRemovable));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), removable.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
        return proposal;
    }

    private static FixProposalDTO buildTuitionBudgetProposal(PlanningStateDTO state,
                                                             UserGoalFixProposalReq req) {
        Integer maxTuition = maxTuitionFromRequest(req);
        if (maxTuition == null || maxTuition <= 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE,
                    REASON_GOAL_UNCLEAR, "这次学费上限还不够明确，需要先确认每年最多能接受多少学费。");
        }

        List<CandidateItemDTO> candidates = candidates(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, candidates);
        Set<String> selectedVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> selectedUnitIds = current.stream()
                .map(PlanVolunteer::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));

        List<PlanVolunteer> overBudget = current.stream()
                .filter(item -> {
                    Integer tuition = tuitionOf(item);
                    return tuition != null && tuition > maxTuition;
                })
                .filter(item -> !item.isLocked())
                .collect(Collectors.toList());
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE,
                "控制学费上限的调整预览");
        if (overBudget.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里没有发现学费超过 " + maxTuition + " 元/年的志愿，本轮不需要为了这个预算调整方案。");
            proposal.setImpact("这条预算可以作为后续报考参考，后续看候选和方案时会继续留意学费。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案没有命中超过预算的志愿。");
            return proposal;
        }

        List<CandidateItemDTO> affordableCandidates = candidates.stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> {
                    Integer tuition = tuitionOf(candidate);
                    return tuition == null || tuition <= maxTuition;
                })
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .sorted(buildCandidatePreviewComparator())
                .collect(Collectors.toList());

        boolean majorGroupMode = isMajorGroupMode(state);
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                overBudget, affordableCandidates, selectedUnitIds, majorGroupMode,
                Math.min(overBudget.size(), affordableCandidates.size()),
                RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE);
        List<PlanVolunteer> remaining = remainingSources(overBudget, pairs);
        proposal.setSummary("当前方案里有 " + overBudget.size() + " 条学费超过 " + maxTuition + " 元/年；本次能替换 "
                + pairs.size() + " 条。");
        proposal.setImpact(remaining.isEmpty()
                ? "确认前不会改动当前方案；确认后会按这次预览处理，并同步刷新方案。"
                : "还有 " + remaining.size() + " 条暂时没有合适补位；本次会处理能替换或移出的部分，剩余部分需要放宽预算或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用不超过预算的候选替换超预算志愿", pairs, majorGroupMode));
        }
        if (!remaining.isEmpty()) {
            proposal.getActions().add(removeAction("学费超过预算且暂未找到补位的志愿", remaining));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), overBudget.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
        return proposal;
    }

    private static FixProposalDTO buildMustIncludeProposal(PlanningStateDTO state,
                                                           UserGoalFixProposalReq req,
                                                           String scopeLabel,
                                                           List<PlanVolunteer> current,
                                                           List<PlanVolunteer> currentMatches,
                                                           List<CandidateItemDTO> candidateMatches,
                                                           Set<String> selectedUnitIds) {
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE,
                "至少保留“" + scopeLabel + "”的调整预览");
        if (!currentMatches.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里已经有 " + currentMatches.size() + " 条“" + scopeLabel + "”相关选择，本轮不需要为了这个目标调整方案。");
            proposal.setImpact("如果还想提高这个方向的优先级，可以继续要求我生成更偏这个方向的调整预览。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案已覆盖这个方向。");
            return proposal;
        }
        if (candidateMatches.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE,
                    REASON_TARGET_NOT_FOUND, "当前方案里还没有“" + scopeLabel + "”，候选池里也暂时没有找到合适补入选择。");
        }
        boolean majorGroupMode = isMajorGroupMode(state);
        if (isCurrentPlanAtOrAboveTargetCount(state)) {
            List<PlanVolunteer> removable = current.stream()
                    .filter(item -> !item.isLocked())
                    .sorted(buildReplacementSourceComparator())
                    .collect(Collectors.toList());
            List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                    removable, candidateMatches, selectedUnitIds, majorGroupMode, 1,
                    RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE);
            if (!pairs.isEmpty()) {
                proposal.setSummary("当前方案里还没有“" + scopeLabel + "”；方案数量已满，已先找到 1 组低优先级项替换预览。");
                proposal.setImpact("确认前不会改动当前方案；确认后会先替换一条低优先级选择，再同步刷新方案。");
                proposal.getActions().add(replaceAction("补入这个方向并替换低优先级志愿", pairs, majorGroupMode));
                markReadyIfActionable(proposal);
                fillDryRun(proposal, current.size(), pairs.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
                return proposal;
            }
        }
        proposal.setSummary("当前方案里还没有“" + scopeLabel + "”；候选池里找到可参考选择，后续可以生成补入预览。");
        proposal.setImpact("确认前不会改动当前方案；确认后会把这个方向补入方案，并同步刷新方案。");
        proposal.getActions().add(addAction("候选池中可补入的选择", Lists.newArrayList(candidateMatches.get(0))));
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), 0, 1, "已生成补入预览，等待确认后再执行。");
        return proposal;
    }

    private static FixProposalDTO buildExcludeProposal(PlanningStateDTO state,
                                                       UserGoalFixProposalReq req,
                                                       String scopeLabel,
                                                       List<PlanVolunteer> current,
                                                       List<PlanVolunteer> currentMatches,
                                                       List<CandidateItemDTO> candidateNonMatches,
                                                       Set<String> selectedUnitIds) {
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE,
                "避开“" + scopeLabel + "”的调整预览");
        if (currentMatches.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里没有发现“" + scopeLabel + "”相关选择，本轮不需要为了这个目标移出志愿。");
            proposal.setImpact("这条要求仍可作为后续报考参考，后续看候选和方案时会继续避开这个方向。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案没有命中需要避开的范围。");
            return proposal;
        }
        List<PlanVolunteer> removable = currentMatches.stream()
                .filter(item -> !item.isLocked())
                .collect(Collectors.toList());
        if (removable.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE,
                    "user_goal_current_hits_locked", "当前方案里有“" + scopeLabel + "”相关选择，但这些条目暂时不能自动移出，需要人工确认后处理。");
        }
        boolean majorGroupMode = isMajorGroupMode(state);
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                removable, candidateNonMatches, selectedUnitIds, majorGroupMode,
                Math.min(removable.size(), candidateNonMatches.size()),
                RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE);
        List<PlanVolunteer> remainingRemovable = remainingSources(removable, pairs);
        proposal.setSummary("当前方案里有 " + currentMatches.size() + " 条命中“" + scopeLabel + "”；本次能替换 "
                + pairs.size() + " 条。");
        proposal.setImpact(remainingRemovable.isEmpty()
                ? "确认前不会改动当前方案；确认后会按这次预览处理，并同步刷新方案。"
                : "还有 " + remainingRemovable.size() + " 条暂时没有合适补位；本次会处理能替换或移出的部分，剩余部分需要放宽条件或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用其他候选替换需要避开的志愿", pairs, majorGroupMode));
        }
        if (!remainingRemovable.isEmpty()) {
            proposal.getActions().add(removeAction("命中避开范围且暂未找到补位的志愿", remainingRemovable));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), removable.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
        return proposal;
    }

    private static void markReadyIfActionable(FixProposalDTO proposal) {
        if (proposal == null || defaultList(proposal.getActions()).isEmpty()) {
            return;
        }
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.setRequiresConfirmation(true);
    }

    private static FixProposalDTO buildUserGoalPreviewBase(PlanningStateDTO state,
                                                           UserGoalFixProposalReq req,
                                                           String strategy,
                                                           String title) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId(buildProposalId(state, req, strategy));
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.USER_GOAL);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setSourceVersionGuard(state == null ? null : state.getVersion());
        proposal.setStatus(RepairProposalTaxonomy.Status.PREVIEW_ONLY);
        proposal.setStrategy(strategy);
        proposal.setTitle(title);
        proposal.setRequiresConfirmation(false);
        return proposal;
    }

    private static FixProposalDTO buildScopeBlockedProposal(PlanningStateDTO state,
                                                            UserGoalFixProposalReq req,
                                                            String strategy,
                                                            String reasonCode,
                                                            String message) {
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, strategy, buildTitle(strategy));
        proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.setSummary(message);
        proposal.setBlockingReason(message);
        proposal.getBlockingReasonCodes().add(reasonCode);
        proposal.getCandidateShortages().add(buildBoundaryShortage(strategy, reasonCode, message));
        proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.getDryRunResult().setMessage(message);
        proposal.setRequiresConfirmation(false);
        return proposal;
    }

    private static FixProposalActionDTO removeAction(String summary, List<PlanVolunteer> volunteers) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail("预计移出 " + volunteers.size() + " 条。");
        action.setVolunteerIds(volunteers.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        action.setUnitIds(volunteers.stream()
                .map(PlanVolunteer::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        action.setRemoveVolunteerIds(action.getVolunteerIds());
        action.setRemoveUnitIds(action.getUnitIds());
        action.setCandidateVolunteerIds(Lists.newArrayList());
        action.setCandidateUnitIds(Lists.newArrayList());
        return action;
    }

    private static FixProposalActionDTO addAction(String summary, List<CandidateItemDTO> candidates) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.ADD_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail("找到 " + candidates.size() + " 条可参考选择。");
        action.setVolunteerIds(candidates.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        action.setUnitIds(candidates.stream()
                .map(RepairCandidateSelector::resolveInitialRecommendationUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        action.setCandidateVolunteerIds(action.getVolunteerIds());
        action.setCandidateUnitIds(action.getUnitIds());
        action.setRemoveVolunteerIds(Lists.newArrayList());
        action.setRemoveUnitIds(Lists.newArrayList());
        return action;
    }

    private static FixProposalActionDTO replaceAction(String summary,
                                                      List<ReplacementPreviewPair> pairs,
                                                      boolean majorGroupMode) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail(buildReplacementActionDetail(pairs));
        action.setRemoveVolunteerIds(pairs.stream()
                .map(pair -> pair.source.getVolunteerId())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        action.setCandidateVolunteerIds(pairs.stream()
                .map(pair -> pair.candidate.getVolunteerId())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        if (majorGroupMode) {
            action.setRemoveUnitIds(pairs.stream()
                    .map(pair -> pair.source.getUnitId())
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .distinct()
                    .collect(Collectors.toList()));
            action.setCandidateUnitIds(pairs.stream()
                    .map(pair -> RepairCandidateSelector.resolveInitialRecommendationUnitId(pair.candidate))
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .distinct()
                    .collect(Collectors.toList()));
        }
        action.setVolunteerIds(action.getRemoveVolunteerIds());
        action.setUnitIds(action.getRemoveUnitIds());
        for (ReplacementPreviewPair pair : pairs) {
            action.getReplacementPairs().add(buildReplacementPair(pair, majorGroupMode));
        }
        return action;
    }

    private static String buildReplacementActionDetail(List<ReplacementPreviewPair> pairs) {
        List<String> previews = defaultList(pairs).stream()
                .limit(3)
                .map(UserGoalProposalBuilder::formatReplacementPreviewPair)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        String base = "预计替换 " + defaultList(pairs).size() + " 组。";
        if (previews.isEmpty()) {
            return base;
        }
        int remainingCount = defaultList(pairs).size() - previews.size();
        String suffix = remainingCount > 0 ? "；另有 " + remainingCount + " 组未展开" : "";
        return base + " 具体预览：" + String.join("；", previews) + suffix + "。";
    }

    private static String formatReplacementPreviewPair(ReplacementPreviewPair pair) {
        if (pair == null) {
            return "";
        }
        String fromText = formatPlanVolunteerBrief(pair.source);
        String toText = formatCandidateBrief(pair.candidate);
        if (Strings.isNullOrEmpty(fromText) || Strings.isNullOrEmpty(toText)) {
            return "";
        }
        String changeText = formatChangeSummary(pair.source == null ? null : pair.source.getCandidate(), pair.candidate);
        return fromText + " -> " + toText + (Strings.isNullOrEmpty(changeText) ? "" : "（" + changeText + "）");
    }

    private static String formatPlanVolunteerBrief(PlanVolunteer volunteer) {
        if (volunteer == null) {
            return "";
        }
        if (volunteer.getCandidate() != null) {
            return formatCandidateBrief(volunteer.getCandidate());
        }
        String label = buildSchoolMajorLabel(volunteer.getSchoolName(), volunteer.getMajorName());
        return Strings.isNullOrEmpty(label) ? firstNonEmpty(volunteer.getUnitId(), volunteer.getVolunteerId()) : label;
    }

    private static String formatCandidateBrief(CandidateItemDTO candidate) {
        if (candidate == null) {
            return "";
        }
        String label = buildSchoolMajorLabel(candidate.getSchoolName(), candidate.getMajorName());
        if (Strings.isNullOrEmpty(label)) {
            label = firstNonEmpty(
                    RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate),
                    candidate.getVolunteerId());
        }
        List<String> tags = Lists.newArrayList(
                candidate.getTier(),
                candidate.getAdmissionRatio() == null ? "" : "录取率" + formatNumber(candidate.getAdmissionRatio()) + "%",
                candidate.getIntentScore() == null ? "" : "匹配" + formatNumber(candidate.getIntentScore()),
                candidate.getFinalScore() == null ? "" : "推荐" + formatNumber(candidate.getFinalScore()),
                candidate.getSchoolRank() == null ? "" : "院校排名" + candidate.getSchoolRank());
        String tagText = tags.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining("/"));
        return Strings.isNullOrEmpty(tagText) ? label : label + "（" + tagText + "）";
    }

    private static String buildSchoolMajorLabel(String schoolName, String majorName) {
        String school = Strings.nullToEmpty(schoolName).trim();
        String major = Strings.nullToEmpty(majorName).trim();
        if (Strings.isNullOrEmpty(school)) {
            return major;
        }
        if (Strings.isNullOrEmpty(major)) {
            return school;
        }
        return school + "-" + major;
    }

    private static String formatChangeSummary(CandidateItemDTO from, CandidateItemDTO to) {
        if (from == null || to == null) {
            return "";
        }
        List<String> changes = Lists.newArrayList(
                formatDelta("录取率", from.getAdmissionRatio(), to.getAdmissionRatio()),
                formatDelta("匹配", from.getIntentScore(), to.getIntentScore()),
                formatDelta("推荐", from.getFinalScore(), to.getFinalScore()),
                formatRankDelta(from.getSchoolRank(), to.getSchoolRank()));
        return changes.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining("，"));
    }

    private static String formatDelta(String label, Double from, Double to) {
        if (from == null || to == null) {
            return "";
        }
        double delta = to - from;
        if (Math.abs(delta) < 0.05D) {
            return "";
        }
        return label + (delta > 0 ? "+" : "") + formatNumber(delta);
    }

    private static String formatRankDelta(Integer from, Integer to) {
        if (from == null || from <= 0 || to == null || to <= 0 || from.equals(to)) {
            return "";
        }
        int delta = to - from;
        return delta > 0 ? "院校排名下降" + delta : "院校排名提升" + Math.abs(delta);
    }

    private static String formatNumber(Double value) {
        if (value == null) {
            return "";
        }
        return String.format(Locale.ROOT, "%.1f", value);
    }

    private static ReplacementPairDTO buildReplacementPair(ReplacementPreviewPair previewPair,
                                                           boolean majorGroupMode) {
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromVolunteerId(previewPair.source.getVolunteerId());
        pair.setToVolunteerId(previewPair.candidate.getVolunteerId());
        if (majorGroupMode) {
            pair.setFromUnitId(previewPair.source.getUnitId());
            pair.setToUnitId(RepairCandidateSelector.resolveInitialRecommendationUnitId(previewPair.candidate));
        }
        pair.getReasonCodes().add(previewPair.reasonCode);
        return pair;
    }

    private static void fillDryRun(FixProposalDTO proposal,
                                   int beforeCount,
                                   int removeCount,
                                   int addPreviewCount,
                                   String message) {
        proposal.getDryRunResult().setStatus(proposal.getStatus());
        proposal.getDryRunResult().setMessage(message);
        proposal.getDryRunResult().setBeforeVolunteerTotal(beforeCount);
        proposal.getDryRunResult().setAfterVolunteerTotal(Math.max(0, beforeCount - removeCount + addPreviewCount));
        proposal.getDryRunResult().setBeforeUnitTotal(beforeCount);
        proposal.getDryRunResult().setAfterUnitTotal(Math.max(0, beforeCount - removeCount + addPreviewCount));
        proposal.getDryRunResult().setAffectedVolunteerCount(removeCount + addPreviewCount);
        proposal.getDryRunResult().setAffectedUnitCount(removeCount + addPreviewCount);
        proposal.getDryRunResult().setRemoveVolunteerCount(removeCount);
        proposal.getDryRunResult().setRemoveUnitCount(removeCount);
        proposal.getDryRunResult().setAddVolunteerCount(addPreviewCount);
        proposal.getDryRunResult().setAddUnitCount(addPreviewCount);
    }

    private static List<ReplacementPreviewPair> buildReplacementPreviewPairs(List<PlanVolunteer> sources,
                                                                             List<CandidateItemDTO> candidates,
                                                                             Set<String> selectedUnitIds,
                                                                             boolean majorGroupMode,
                                                                             int limit,
                                                                             String reasonCode) {
        List<ReplacementPreviewPair> pairs = Lists.newArrayList();
        if (limit <= 0) {
            return pairs;
        }
        List<PlanVolunteer> orderedSources = defaultList(sources).stream()
                .filter(source -> source != null && !source.isLocked())
                .filter(source -> !Strings.isNullOrEmpty(source.getVolunteerId()))
                .sorted(buildReplacementSourceComparator())
                .collect(Collectors.toList());
        List<CandidateItemDTO> remainingCandidates = distinctReplacementCandidates(candidates, majorGroupMode);
        Set<String> usedCandidateVolunteerIds = new LinkedHashSet<String>();
        Set<String> usedCandidateUnitIds = new LinkedHashSet<String>();
        Set<String> currentUnitIds = selectedUnitIds == null ? new LinkedHashSet<String>() : selectedUnitIds;
        for (PlanVolunteer source : orderedSources) {
            if (pairs.size() >= limit || remainingCandidates.isEmpty()) {
                break;
            }
            CandidateItemDTO best = remainingCandidates.stream()
                    .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                    .filter(candidate -> !source.getVolunteerId().equals(candidate.getVolunteerId()))
                    .filter(candidate -> !usedCandidateVolunteerIds.contains(candidate.getVolunteerId()))
                    .filter(candidate -> !majorGroupMode || isCandidateUnitAvailableForReplacement(
                            candidate, source.getUnitId(), currentUnitIds, usedCandidateUnitIds))
                    .min((left, right) -> compareUserGoalReplacementTradeoff(source.getCandidate(), left, right))
                    .orElse(null);
            if (best == null) {
                continue;
            }
            pairs.add(new ReplacementPreviewPair(source, best, reasonCode));
            usedCandidateVolunteerIds.add(best.getVolunteerId());
            String candidateUnitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(best);
            if (!Strings.isNullOrEmpty(candidateUnitId)) {
                usedCandidateUnitIds.add(candidateUnitId);
            }
            remainingCandidates.remove(best);
        }
        return pairs;
    }

    private static List<CandidateItemDTO> distinctReplacementCandidates(List<CandidateItemDTO> candidates,
                                                                        boolean majorGroupMode) {
        Set<String> seenKeys = new LinkedHashSet<String>();
        List<CandidateItemDTO> result = Lists.newArrayList();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                continue;
            }
            String key = majorGroupMode
                    ? firstNonEmpty(RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate), candidate.getVolunteerId())
                    : candidate.getVolunteerId();
            if (seenKeys.add(key)) {
                result.add(candidate);
            }
        }
        return result;
    }

    private static int compareUserGoalReplacementTradeoff(CandidateItemDTO source,
                                                          CandidateItemDTO left,
                                                          CandidateItemDTO right) {
        int compare = Integer.compare(
                RepairReplacementTradeoffSupport.majorSimilarityLevel(source, left),
                RepairReplacementTradeoffSupport.majorSimilarityLevel(source, right));
        if (compare != 0) {
            return compare;
        }
        compare = Integer.compare(
                RepairReplacementTradeoffSupport.schoolRankDowngradePenalty(source, left),
                RepairReplacementTradeoffSupport.schoolRankDowngradePenalty(source, right));
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getIntentScore(),
                        left == null ? null : left.getIntentScore()),
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getIntentScore(),
                        right == null ? null : right.getIntentScore()));
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getFinalScore(),
                        left == null ? null : left.getFinalScore()),
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getFinalScore(),
                        right == null ? null : right.getFinalScore()));
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(left == null ? null : left.getIntentScore(), right == null ? null : right.getIntentScore());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(left == null ? null : left.getAdmissionRatio(), right == null ? null : right.getAdmissionRatio());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(left == null ? null : left.getFinalScore(), right == null ? null : right.getFinalScore());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableIntegerAsc(left == null ? null : left.getSchoolRank(), right == null ? null : right.getSchoolRank());
        if (compare != 0) {
            return compare;
        }
        return Strings.nullToEmpty(left == null ? null : left.getVolunteerId())
                .compareTo(Strings.nullToEmpty(right == null ? null : right.getVolunteerId()));
    }

    private static boolean isCandidateUnitAvailableForReplacement(CandidateItemDTO candidate,
                                                                  String sourceUnitId,
                                                                  Set<String> currentUnitIds,
                                                                  Set<String> usedCandidateUnitIds) {
        String candidateUnitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
        if (Strings.isNullOrEmpty(candidateUnitId)) {
            return false;
        }
        if (candidateUnitId.equals(sourceUnitId)) {
            return false;
        }
        return !defaultSet(currentUnitIds).contains(candidateUnitId)
                && !defaultSet(usedCandidateUnitIds).contains(candidateUnitId);
    }

    private static List<PlanVolunteer> remainingSources(List<PlanVolunteer> sources,
                                                        List<ReplacementPreviewPair> pairs) {
        Set<String> pairedVolunteerIds = defaultList(pairs).stream()
                .map(pair -> pair.source.getVolunteerId())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        return defaultList(sources).stream()
                .filter(source -> source != null && !pairedVolunteerIds.contains(source.getVolunteerId()))
                .collect(Collectors.toList());
    }

    private static Comparator<PlanVolunteer> buildReplacementSourceComparator() {
        return Comparator
                .comparing((PlanVolunteer item) -> metricOf(item, CandidateItemDTO::getAdmissionRatio), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> metricOf(item, CandidateItemDTO::getFinalScore), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> metricOf(item, CandidateItemDTO::getIntentScore), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> metricOf(item, candidate -> candidate.getSchoolRank() == null ? null : candidate.getSchoolRank().doubleValue()),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(PlanVolunteer::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Double metricOf(PlanVolunteer item,
                                   java.util.function.Function<CandidateItemDTO, Double> mapper) {
        if (item == null || item.getCandidate() == null || mapper == null) {
            return null;
        }
        return mapper.apply(item.getCandidate());
    }

    private static Integer tuitionOf(PlanVolunteer item) {
        if (item == null || item.getCandidate() == null) {
            return null;
        }
        return item.getCandidate().getTuitionPerYear();
    }

    private static Integer tuitionOf(CandidateItemDTO item) {
        return item == null ? null : item.getTuitionPerYear();
    }

    private static boolean isMajorGroupMode(PlanningStateDTO state) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        return candidatePoolState != null && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static boolean isCurrentPlanAtOrAboveTargetCount(PlanningStateDTO state) {
        Integer requiredCount = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        if (requiredCount == null || requiredCount <= 0) {
            return false;
        }
        int currentCount = isMajorGroupMode(state)
                ? currentPlanUnitCount(state)
                : currentPlanVolunteerCount(state);
        return currentCount >= requiredCount;
    }

    private static int currentPlanVolunteerCount(PlanningStateDTO state) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()) {
            return defaultList(state.getOrderedPlanState().getItems()).size();
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getItems()).isEmpty()) {
            return defaultList(state.getWorkingPlanState().getItems()).size();
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getOrderedPlanState().getUnits()).stream()
                    .mapToInt(unit -> defaultList(unit == null ? null : unit.getMajorItems()).size())
                    .sum();
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getWorkingPlanState().getUnits()).stream()
                    .mapToInt(unit -> defaultList(unit == null ? null : unit.getMajorItems()).size())
                    .sum();
        }
        return 0;
    }

    private static int currentPlanUnitCount(PlanningStateDTO state) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getOrderedPlanState().getUnits()).size();
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getWorkingPlanState().getUnits()).size();
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()) {
            return currentPlanVolunteerCount(state);
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getItems()).isEmpty()) {
            return currentPlanVolunteerCount(state);
        }
        return 0;
    }

    private static CandidateShortageDTO buildBoundaryShortage(String reasonCode, String message) {
        return buildBoundaryShortage(RepairProposalTaxonomy.Strategy.CANNOT_SATISFY, reasonCode, message);
    }

    private static CandidateShortageDTO buildBoundaryShortage(String strategy, String reasonCode, String message) {
        CandidateShortageDTO shortage = new CandidateShortageDTO();
        shortage.setStrategy(strategy);
        shortage.setScope("proposal_engine");
        shortage.setReasonCode(reasonCode);
        shortage.setMessage(message);
        return shortage;
    }

    private static String buildTitle(String goalType) {
        if ("only_keep_scope".equals(goalType)) {
            return "只保留范围的方案调整暂不自动执行";
        }
        if ("must_include_scope".equals(goalType)) {
            return "至少保留范围的方案调整暂不自动执行";
        }
        if ("exclude_scope".equals(goalType)) {
            return "排除范围的方案调整暂不自动执行";
        }
        if ("mixed_adjustment".equals(goalType)) {
            return "复合方案调整暂不自动执行";
        }
        if ("tuition_budget_scope".equals(goalType)) {
            return "学费预算调整暂不自动执行";
        }
        return "方案调整目标暂不自动执行";
    }

    private static String buildMessage(String goalType, String reasonCode) {
        if (REASON_SOURCE_VERSION_MISMATCH.equals(reasonCode)) {
            return "当前方案已经变化，需要重新读取方案后再生成调整预览。";
        }
        if (REASON_GOAL_UNCLEAR.equals(reasonCode)) {
            return "这次调整目标还不够明确，需要先确认要保留、补入或排除的范围。";
        }
        if (REASON_TARGET_NOT_FOUND.equals(reasonCode)) {
            return "当前方案和候选池里暂时没有找到符合目标范围的选择，不能直接生成调整预览。";
        }
        if (REASON_ENTITY_NEEDS_CLARIFICATION.equals(reasonCode)) {
            return "这次提到的范围还不够明确，需要先确认具体专业、院校或地域后再生成调整预览。";
        }
        if ("only_keep_scope".equals(goalType)) {
            return "已识别为“只保留某个范围”的复合目标，但还需要先计算当前方案中哪些保留、哪些移出、候选是否能补足，以及调整后的风险变化；当前不会自动修改方案。";
        }
        if ("must_include_scope".equals(goalType)) {
            return "已识别为“至少保留某个范围”的复合目标，但还需要先检查当前方案是否已有命中、候选是否能补入，以及是否需要替换低优先级项；当前不会自动修改方案。";
        }
        if ("exclude_scope".equals(goalType)) {
            return "已识别为“避开某个范围”的复合目标，但还需要先定位当前方案命中项、确认专业/院校/地域粒度，并判断删除或替换后的数量和风险；当前不会自动修改方案。";
        }
        if ("mixed_adjustment".equals(goalType)) {
            return "已识别为多目标方案调整，但需要先拆成可验证的保留、排除、补入、替换或重排动作；当前不会自动修改方案。";
        }
        if ("tuition_budget_scope".equals(goalType)) {
            return "已识别为学费预算调整，但需要先定位当前方案里超过预算的志愿，并判断是否有合适补位；当前不会自动修改方案。";
        }
        return "复合方案调整需要先生成可验证的调整预览；当前不会自动修改方案。";
    }

    private static String normalizeGoalType(String goalType) {
        return Strings.nullToEmpty(goalType).trim();
    }

    private static Integer maxTuitionFromRequest(UserGoalFixProposalReq req) {
        if (req == null) {
            return null;
        }
        Integer fromContext = intFromObject(req.getContext() == null ? null : req.getContext().get("maxTuitionPerYear"));
        if (fromContext != null) {
            return fromContext;
        }
        for (UserGoalFixProposalReq.ScopeDTO scope : defaultList(req.getTargetScopes())) {
            Integer value = intFromObject(scope == null || scope.getEvidence() == null ? null : scope.getEvidence().get("maxTuitionPerYear"));
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private static Integer intFromObject(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        String digits = Strings.nullToEmpty(String.valueOf(value)).replaceAll("[^0-9]", "");
        if (Strings.isNullOrEmpty(digits)) {
            return null;
        }
        try {
            return Integer.parseInt(digits);
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private static List<UserGoalFixProposalReq.ScopeDTO> scopesForGoal(UserGoalFixProposalReq req, String goalType) {
        if (req == null) {
            return Lists.newArrayList();
        }
        if (RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE.equals(goalType)) {
            return req.getNegativeScopes() == null || req.getNegativeScopes().isEmpty()
                    ? defaultList(req.getTargetScopes()) : defaultList(req.getNegativeScopes());
        }
        return defaultList(req.getTargetScopes());
    }

    private static List<ScopeMatcher> buildScopeMatchers(List<UserGoalFixProposalReq.ScopeDTO> scopes) {
        return defaultList(scopes).stream()
                .map(ScopeMatcher::from)
                .filter(scope -> !Strings.isNullOrEmpty(scope.getValue()))
                .collect(Collectors.toList());
    }

    private static String scopeLabel(List<ScopeMatcher> scopes) {
        String label = scopes.stream()
                .map(ScopeMatcher::getValue)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.joining("、"));
        return Strings.isNullOrEmpty(label) ? "目标范围" : label;
    }

    private static boolean matchesAny(PlanVolunteer item, List<ScopeMatcher> scopes) {
        return defaultList(scopes).stream().anyMatch(scope -> scope.matches(item));
    }

    private static boolean matchesAny(CandidateItemDTO candidate, List<ScopeMatcher> scopes) {
        return defaultList(scopes).stream().anyMatch(scope -> scope.matches(candidate));
    }

    private static List<CandidateItemDTO> candidates(PlanningStateDTO state) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        return defaultList(candidatePoolState == null ? null : candidatePoolState.getItems());
    }

    private static List<PlanVolunteer> currentPlanVolunteers(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        List<PlanVolunteer> result = Lists.newArrayList();
        if (state == null) {
            return result;
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()) {
            for (OrderedItemDTO item : defaultList(state.getOrderedPlanState().getItems())) {
                result.add(PlanVolunteer.from(item, RepairCandidateSelector.findCandidate(candidates, item.getVolunteerId()), candidates));
            }
            return result;
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getUnits()).isEmpty()) {
            for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
                for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                    result.add(PlanVolunteer.from(unit, major, RepairCandidateSelector.findCandidate(candidates, major.getVolunteerId()), candidates));
                }
            }
            return result;
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getItems()).isEmpty()) {
            for (DraftItemDTO item : defaultList(state.getWorkingPlanState().getItems())) {
                result.add(PlanVolunteer.from(item, RepairCandidateSelector.findCandidate(candidates, item.getVolunteerId()), candidates));
            }
            return result;
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getUnits()).isEmpty()) {
            for (DraftUnitDTO unit : defaultList(state.getWorkingPlanState().getUnits())) {
                for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                    result.add(PlanVolunteer.from(unit, major, RepairCandidateSelector.findCandidate(candidates, major.getVolunteerId()), candidates));
                }
            }
        }
        return result;
    }

    private static Comparator<CandidateItemDTO> buildCandidatePreviewComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(item -> item.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(item -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(item -> item.getSchoolRank(), Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static int compareNullableDoubleDesc(Double left, Double right) {
        if (left == null && right == null) {
            return 0;
        }
        if (left == null) {
            return 1;
        }
        if (right == null) {
            return -1;
        }
        return Double.compare(right, left);
    }

    private static int compareNullableIntegerAsc(Integer left, Integer right) {
        if (left == null && right == null) {
            return 0;
        }
        if (left == null) {
            return 1;
        }
        if (right == null) {
            return -1;
        }
        return Integer.compare(left, right);
    }

    private static String buildProposalId(PlanningStateDTO state, UserGoalFixProposalReq req, String reasonCode) {
        String raw = String.join("|",
                String.valueOf(state == null ? null : state.getSessionId()),
                String.valueOf(state == null ? null : state.getVersion()),
                String.valueOf(req == null ? null : req.getGoalType()),
                String.valueOf(req == null ? null : req.getUserOriginalText()),
                String.valueOf(reasonCode));
        return "ugp_" + UUID.nameUUIDFromBytes(raw.getBytes(StandardCharsets.UTF_8)).toString().replace("-", "").substring(0, 16);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static <T> Set<T> defaultSet(Set<T> values) {
        return values == null ? new LinkedHashSet<T>() : values;
    }

    private static String firstNonEmpty(String... values) {
        for (String value : values) {
            if (!Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())) {
                return value.trim();
            }
        }
        return "";
    }

    private static String normalizeText(String text) {
        return Strings.nullToEmpty(text).trim().toLowerCase(Locale.ROOT).replaceAll("\\s+", "");
    }

    private static boolean containsLoose(String text, String value) {
        String normalizedText = normalizeText(text);
        String normalizedValue = normalizeText(value);
        if (Strings.isNullOrEmpty(normalizedText) || Strings.isNullOrEmpty(normalizedValue)) {
            return false;
        }
        return normalizedText.contains(normalizedValue) || normalizedValue.contains(normalizedText);
    }

    private static boolean containsAny(List<String> texts, String value) {
        return defaultList(texts).stream().anyMatch(text -> containsLoose(text, value));
    }

    private static boolean containsAny(String value, String... texts) {
        for (String text : texts) {
            if (containsLoose(text, value)) {
                return true;
            }
        }
        return false;
    }

    private static final class ScopeMatcher {
        private final String entityType;
        private final String value;
        private final String scopeLevel;
        private final String resolutionStatus;

        private ScopeMatcher(String entityType, String value, String scopeLevel, String resolutionStatus) {
            this.entityType = entityType;
            this.value = value;
            this.scopeLevel = scopeLevel;
            this.resolutionStatus = resolutionStatus;
        }

        static ScopeMatcher from(UserGoalFixProposalReq.ScopeDTO scope) {
            if (scope == null) {
                return new ScopeMatcher("", "", "", "");
            }
            String entityType = normalizeEntityType(firstNonEmpty(scope.getEntityType(), scope.getScopeType()));
            String value = firstNonEmpty(scope.getNormalizedName(), scope.getName(), scope.getRawText());
            String scopeLevel = firstNonEmpty(
                    scope.getScopeLevel(),
                    scope.getEvidence() == null ? null : String.valueOf(scope.getEvidence().get("scopeLevel")));
            return new ScopeMatcher(entityType, value, normalizeScopeLevel(scopeLevel),
                    Strings.nullToEmpty(scope.getResolutionStatus()).trim());
        }

        String getValue() {
            return value;
        }

        boolean needsClarification() {
            return !isSupportedEntityType(entityType)
                    || "unknown".equals(resolutionStatus)
                    || "multiple_match".equals(resolutionStatus)
                    || "needs_clarification".equals(resolutionStatus)
                    || "ambiguous".equals(resolutionStatus);
        }

        boolean matches(PlanVolunteer item) {
            if (item == null) {
                return false;
            }
            CandidateItemDTO candidate = item.getCandidate();
            if (candidate != null && matches(candidate)) {
                return true;
            }
            if ("major".equals(entityType)) {
                return containsLoose(item.getMajorName(), value);
            }
            if ("school".equals(entityType)) {
                return containsLoose(item.getSchoolName(), value);
            }
            if ("program_type".equals(entityType)) {
                return matchesProgramType(
                        value,
                        item.getSchoolName(),
                        item.getMajorName(),
                        candidate);
            }
            return false;
        }

        boolean matches(CandidateItemDTO candidate) {
            if (candidate == null) {
                return false;
            }
            if ("major".equals(entityType)) {
                return containsLoose(candidate.getMajorName(), value)
                        || containsLoose(candidate.getMajorCategory(), value)
                        || containsLoose(candidate.getMajorDiscipline(), value)
                        || containsLoose(candidate.getMajorLevel(), value)
                        || containsAny(candidate.getMajorPlanTags(), value)
                        || containsAny(candidate.getMajorRankTags(), value);
            }
            if ("school".equals(entityType)) {
                return containsLoose(candidate.getDisplaySchoolName(), value)
                        || containsLoose(candidate.getSchoolName(), value);
            }
            if ("region".equals(entityType)) {
                return matchesRegion(candidate);
            }
            if ("tag".equals(entityType) || "risk".equals(entityType)) {
                return containsAny(candidate.getReasonCodes(), value)
                        || containsAny(candidate.getRiskFlags(), value)
                        || containsAny(candidate.getSchoolRankTags(), value)
                        || containsAny(candidate.getSchoolBasicTags(), value)
                        || containsAny(candidate.getSchoolPopupTags(), value)
                        || containsAny(candidate.getMajorPlanTags(), value)
                        || containsAny(candidate.getMajorRankTags(), value);
            }
            if ("program_type".equals(entityType)) {
                return matchesProgramType(
                        value,
                        candidate.getSchoolName(),
                        candidate.getDisplaySchoolName(),
                        candidate.getMajorName(),
                        candidate.getSchoolNature(),
                        candidate.getSchoolCategory(),
                        candidate.getSchoolBatch(),
                        candidate.getReasonCodes(),
                        candidate.getRiskFlags(),
                        candidate.getSchoolRankTags(),
                        candidate.getSchoolBasicTags(),
                        candidate.getSchoolPopupTags(),
                        candidate.getMajorPlanTags(),
                        candidate.getMajorRankTags());
            }
            return containsLoose(candidate.getMajorName(), value)
                    || containsLoose(candidate.getSchoolName(), value)
                    || containsLoose(candidate.getProvinceName(), value)
                    || containsLoose(candidate.getCityName(), value);
        }

        private boolean matchesRegion(CandidateItemDTO candidate) {
            if (candidate == null) {
                return false;
            }
            if ("area".equals(scopeLevel)) {
                if (RegionScopeSupport.matchesRegionScope(value, candidate.getProvinceName(), candidate.getCityName())) {
                    return true;
                }
                return containsLoose(candidate.getProvinceName(), value)
                        || containsLoose(candidate.getCityName(), value);
            }
            if ("province".equals(scopeLevel)) {
                return containsLoose(candidate.getProvinceName(), value);
            }
            if ("city".equals(scopeLevel)) {
                return containsLoose(candidate.getCityName(), value);
            }
            return containsLoose(candidate.getProvinceName(), value)
                    || containsLoose(candidate.getCityName(), value);
        }

        private static boolean matchesProgramType(String value, String schoolName, String majorName, CandidateItemDTO candidate) {
            if (candidate == null) {
                return containsAny(value, schoolName, majorName);
            }
            return matchesProgramType(
                    value,
                    schoolName,
                    candidate.getDisplaySchoolName(),
                    majorName,
                    candidate.getSchoolNature(),
                    candidate.getSchoolCategory(),
                    candidate.getSchoolBatch(),
                    candidate.getReasonCodes(),
                    candidate.getRiskFlags(),
                    candidate.getSchoolRankTags(),
                    candidate.getSchoolBasicTags(),
                    candidate.getSchoolPopupTags(),
                    candidate.getMajorPlanTags(),
                    candidate.getMajorRankTags());
        }

        private static boolean matchesProgramType(String value, Object... fields) {
            for (Object field : fields) {
                if (field instanceof String && containsLoose((String) field, value)) {
                    return true;
                }
                if (field instanceof List<?>) {
                    List<String> values = ((List<?>) field).stream()
                            .filter(Objects::nonNull)
                            .map(String::valueOf)
                            .collect(Collectors.toList());
                    if (containsAny(values, value)) {
                        return true;
                    }
                }
            }
            return false;
        }

        private static String normalizeEntityType(String type) {
            String text = Strings.nullToEmpty(type).trim().toLowerCase(Locale.ROOT);
            if ("province".equals(text) || "city".equals(text) || "area".equals(text)
                    || "province_keyword".equals(text)) {
                return "region";
            }
            if ("major_keyword".equals(text) || "source_major".equals(text) || "source_major_name".equals(text)) {
                return "major";
            }
            if ("school_keyword".equals(text)) {
                return "school";
            }
            if ("major_tag".equals(text) || "school_tag".equals(text)) {
                return "tag";
            }
            if ("review_issue".equals(text)) {
                return "risk";
            }
            if ("project_type".equals(text) || "admission_type".equals(text)
                    || "enrollment_type".equals(text) || "program".equals(text)
                    || "project".equals(text)) {
                return "program_type";
            }
            return text;
        }

        private static String normalizeScopeLevel(String level) {
            String text = Strings.nullToEmpty(level).trim().toLowerCase(Locale.ROOT);
            if ("province".equals(text) || "city".equals(text) || "area".equals(text)) {
                return text;
            }
            return "";
        }

        private static boolean isSupportedEntityType(String type) {
            return "major".equals(type)
                    || "school".equals(type)
                    || "region".equals(type)
                    || "tag".equals(type)
                    || "risk".equals(type)
                    || "program_type".equals(type);
        }

        private static String firstNonEmpty(String... values) {
            for (String value : values) {
                if (!Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())) {
                    return value.trim();
                }
            }
            return "";
        }
    }

    private static final class PlanVolunteer {
        private final String volunteerId;
        private final String unitId;
        private final String schoolName;
        private final String majorName;
        private final boolean locked;
        private final CandidateItemDTO candidate;

        private PlanVolunteer(String volunteerId,
                              String unitId,
                              String schoolName,
                              String majorName,
                              boolean locked,
                              CandidateItemDTO candidate) {
            this.volunteerId = volunteerId;
            this.unitId = unitId;
            this.schoolName = schoolName;
            this.majorName = majorName;
            this.locked = locked;
            this.candidate = candidate;
        }

        static PlanVolunteer from(OrderedItemDTO item, CandidateItemDTO candidate, List<CandidateItemDTO> candidates) {
            return new PlanVolunteer(
                    item == null ? null : item.getVolunteerId(),
                    item == null ? null : RepairCandidateSelector.resolveUnitId(item.getVolunteerId(), candidates),
                    firstNonEmpty(candidate == null ? null : candidate.getSchoolName(), item == null ? null : item.getSchoolName()),
                    firstNonEmpty(candidate == null ? null : candidate.getMajorName(), item == null ? null : item.getMajorName()),
                    item != null && Boolean.TRUE.equals(item.getLocked()),
                    candidate);
        }

        static PlanVolunteer from(DraftItemDTO item, CandidateItemDTO candidate, List<CandidateItemDTO> candidates) {
            return new PlanVolunteer(
                    item == null ? null : item.getVolunteerId(),
                    item == null ? null : RepairCandidateSelector.resolveUnitId(item.getVolunteerId(), candidates),
                    firstNonEmpty(candidate == null ? null : candidate.getSchoolName(), item == null ? null : item.getSchoolName()),
                    firstNonEmpty(candidate == null ? null : candidate.getMajorName(), item == null ? null : item.getMajorName()),
                    item != null && Boolean.TRUE.equals(item.getLocked()),
                    candidate);
        }

        static PlanVolunteer from(OrderedUnitDTO unit,
                                  PlanningUnitMajorDTO major,
                                  CandidateItemDTO candidate,
                                  List<CandidateItemDTO> candidates) {
            return new PlanVolunteer(
                    major == null ? null : major.getVolunteerId(),
                    firstNonEmpty(unit == null ? null : unit.getUnitId(), major == null ? null : RepairCandidateSelector.resolveUnitId(major.getVolunteerId(), candidates)),
                    firstNonEmpty(candidate == null ? null : candidate.getSchoolName(), unit == null ? null : unit.getSchoolName()),
                    firstNonEmpty(candidate == null ? null : candidate.getMajorName(), major == null ? null : major.getMajorName()),
                    unit != null && Boolean.TRUE.equals(unit.getLocked()),
                    candidate);
        }

        static PlanVolunteer from(DraftUnitDTO unit,
                                  PlanningUnitMajorDTO major,
                                  CandidateItemDTO candidate,
                                  List<CandidateItemDTO> candidates) {
            return new PlanVolunteer(
                    major == null ? null : major.getVolunteerId(),
                    firstNonEmpty(unit == null ? null : unit.getUnitId(), major == null ? null : RepairCandidateSelector.resolveUnitId(major.getVolunteerId(), candidates)),
                    firstNonEmpty(candidate == null ? null : candidate.getSchoolName(), unit == null ? null : unit.getSchoolName()),
                    firstNonEmpty(candidate == null ? null : candidate.getMajorName(), major == null ? null : major.getMajorName()),
                    unit != null && Boolean.TRUE.equals(unit.getLocked()),
                    candidate);
        }

        String getVolunteerId() {
            return volunteerId;
        }

        String getUnitId() {
            return unitId;
        }

        String getSchoolName() {
            return schoolName;
        }

        String getMajorName() {
            return majorName;
        }

        boolean isLocked() {
            return locked;
        }

        CandidateItemDTO getCandidate() {
            return candidate;
        }

        private static String firstNonEmpty(String... values) {
            for (String value : values) {
                if (!Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())) {
                    return value.trim();
                }
            }
            return "";
        }
    }

    private static final class ReplacementPreviewPair {
        private final PlanVolunteer source;
        private final CandidateItemDTO candidate;
        private final String reasonCode;

        private ReplacementPreviewPair(PlanVolunteer source, CandidateItemDTO candidate, String reasonCode) {
            this.source = source;
            this.candidate = candidate;
            this.reasonCode = reasonCode;
        }
    }
}
