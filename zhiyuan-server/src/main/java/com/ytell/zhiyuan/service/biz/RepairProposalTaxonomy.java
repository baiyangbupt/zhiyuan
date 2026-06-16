package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * Central repair taxonomy shared by review proposal generation, dry-run and apply.
 *
 * DTO fields intentionally remain strings for API compatibility. Runtime code should
 * use this taxonomy instead of scattering literal strategy/action/status checks.
 */
final class RepairProposalTaxonomy {

    private RepairProposalTaxonomy() {
    }

    static final class Status {
        static final String READY = "ready";
        static final String PREVIEW_ONLY = "preview_only";
        static final String BLOCKED = "blocked";
        static final String INFO = "info";
        static final String EMPTY = "empty";
        static final String BLOCKED_OR_INFO = "blocked_or_info";

        private Status() {
        }
    }

    static final class ProposalSource {
        static final String REVIEW_CHECK = "review_check";
        static final String USER_GOAL = "user_goal";

        private ProposalSource() {
        }
    }

    static final class Strategy {
        static final String FILL_MISSING_COUNT = "fill_missing_count";
        static final String ADD_SAFETY_ITEMS = "add_safety_items";
        static final String REBALANCE_TIER_RATIO = "rebalance_tier_ratio";
        static final String FILL_PROBABILITY_GAP = "fill_probability_gap";
        static final String SORT_BY_PROBABILITY = "sort_by_probability";
        static final String REMOVE_RISK_ITEMS = "remove_risk_items";
        static final String REPLACE_RISK_ITEMS = "replace_risk_items";
        static final String ADJUST_MAJOR_GROUP_INNER_SAFETY = "adjust_major_group_inner_safety";
        static final String ONLY_KEEP_SCOPE = "only_keep_scope";
        static final String MUST_INCLUDE_SCOPE = "must_include_scope";
        static final String EXCLUDE_SCOPE = "exclude_scope";
        static final String TUITION_BUDGET_SCOPE = "tuition_budget_scope";
        static final String NO_OP = "no_op";
        static final String CANNOT_SATISFY = "cannot_satisfy";

        private Strategy() {
        }
    }

    static final class ActionType {
        static final String FILL_TOTAL_COUNT = "fill_total_count";
        static final String ADD_VOLUNTEERS = "add_volunteers";
        static final String REMOVE_VOLUNTEERS = "remove_volunteers";
        static final String REPLACE_VOLUNTEERS = "replace_volunteers";
        static final String REORDER_VOLUNTEERS = "reorder_volunteers";
        static final String ADJUST_MAJOR_GROUP_INNER_SAFETY = "adjust_major_group_inner_safety";
        static final String NO_OP = "no_op";

        private ActionType() {
        }
    }

    static final class CompensationActionType {
        static final String FILL_TOTAL_COUNT = "fill_total_count";
        static final String ADD_LOCAL_PROTECT = "add_local_protect";
        static final String REBALANCE_PROTECT_RATIO = "rebalance_protect_ratio";
        static final String FILL_PROBABILITY_GAP = "fill_probability_gap";

        private CompensationActionType() {
        }
    }

    private static final Set<String> APPLYABLE_STRATEGIES = unmodifiableSet(
            Strategy.FILL_MISSING_COUNT,
            Strategy.SORT_BY_PROBABILITY,
            Strategy.REMOVE_RISK_ITEMS,
            Strategy.REPLACE_RISK_ITEMS,
            Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY
    );

    private static final Set<String> USER_GOAL_APPLYABLE_STRATEGIES = unmodifiableSet(
            Strategy.ONLY_KEEP_SCOPE,
            Strategy.MUST_INCLUDE_SCOPE,
            Strategy.EXCLUDE_SCOPE,
            Strategy.TUITION_BUDGET_SCOPE
    );

    private static final Set<String> PREVIEW_ONLY_STRATEGIES = unmodifiableSet(
            Strategy.ADD_SAFETY_ITEMS,
            Strategy.REBALANCE_TIER_RATIO,
            Strategy.FILL_PROBABILITY_GAP,
            Strategy.ONLY_KEEP_SCOPE,
            Strategy.MUST_INCLUDE_SCOPE,
            Strategy.EXCLUDE_SCOPE,
            Strategy.TUITION_BUDGET_SCOPE
    );

    private static final Map<String, String> STRATEGY_ALIASES = buildStrategyAliases();
    private static final Map<String, String> ACTION_TYPE_ALIASES = buildActionTypeAliases();
    private static final Map<String, Set<String>> STRATEGY_ACTION_TYPES = buildStrategyActionTypes();

    static String normalizeStrategy(String strategy) {
        String text = normalizeText(strategy);
        if (Strings.isNullOrEmpty(text)) {
            return text;
        }
        String alias = STRATEGY_ALIASES.get(text);
        return Strings.isNullOrEmpty(alias) ? text : alias;
    }

    static String normalizeActionType(String actionType) {
        String text = normalizeText(actionType);
        if (Strings.isNullOrEmpty(text)) {
            return text;
        }
        String alias = ACTION_TYPE_ALIASES.get(text);
        return Strings.isNullOrEmpty(alias) ? text : alias;
    }

    static String normalizeStatus(String status) {
        String text = normalizeText(status);
        if (Strings.isNullOrEmpty(text)) {
            return Status.PREVIEW_ONLY;
        }
        if (Strategy.CANNOT_SATISFY.equals(text)) {
            return Status.BLOCKED;
        }
        if (Strategy.NO_OP.equals(text)) {
            return Status.INFO;
        }
        return text;
    }

    static String normalizeProposalSource(String source) {
        String text = normalizeText(source);
        if (Strings.isNullOrEmpty(text)) {
            return ProposalSource.REVIEW_CHECK;
        }
        return text;
    }

    static boolean isReviewCheckSource(String source) {
        return ProposalSource.REVIEW_CHECK.equals(normalizeProposalSource(source));
    }

    static boolean isUserGoalSource(String source) {
        return ProposalSource.USER_GOAL.equals(normalizeProposalSource(source));
    }

    static boolean isReadyStatus(String status) {
        return Status.READY.equals(normalizeStatus(status));
    }

    static boolean isPreviewOnlyStatus(String status) {
        return Status.PREVIEW_ONLY.equals(normalizeStatus(status));
    }

    static boolean isBlockedStatus(String status) {
        return Status.BLOCKED.equals(normalizeStatus(status));
    }

    static boolean isInfoStatus(String status) {
        return Status.INFO.equals(normalizeStatus(status));
    }

    static boolean isApplyableStrategy(String strategy) {
        return APPLYABLE_STRATEGIES.contains(normalizeStrategy(strategy));
    }

    static boolean isUserGoalApplyableStrategy(String strategy) {
        return USER_GOAL_APPLYABLE_STRATEGIES.contains(normalizeStrategy(strategy));
    }

    static boolean isPreviewOnlyStrategy(String strategy) {
        return PREVIEW_ONLY_STRATEGIES.contains(normalizeStrategy(strategy));
    }

    static boolean isCannotSatisfyStrategy(String strategy) {
        return Strategy.CANNOT_SATISFY.equals(normalizeStrategy(strategy));
    }

    static boolean isNoOpStrategy(String strategy) {
        return Strategy.NO_OP.equals(normalizeStrategy(strategy));
    }

    static boolean isStructuralPreviewStrategy(String strategy) {
        String normalized = normalizeStrategy(strategy);
        return Strategy.REBALANCE_TIER_RATIO.equals(normalized)
                || Strategy.FILL_PROBABILITY_GAP.equals(normalized);
    }

    static boolean actionAllowedForStrategy(String strategy, String actionType) {
        Set<String> allowed = STRATEGY_ACTION_TYPES.get(normalizeStrategy(strategy));
        return allowed != null && allowed.contains(normalizeActionType(actionType));
    }

    static String strategyForCompensationActionType(String actionType) {
        String normalized = normalizeText(actionType);
        if (CompensationActionType.FILL_TOTAL_COUNT.equals(normalized)) {
            return Strategy.FILL_MISSING_COUNT;
        }
        if (CompensationActionType.ADD_LOCAL_PROTECT.equals(normalized)) {
            return Strategy.ADD_SAFETY_ITEMS;
        }
        if (CompensationActionType.REBALANCE_PROTECT_RATIO.equals(normalized)) {
            return Strategy.REBALANCE_TIER_RATIO;
        }
        if (CompensationActionType.FILL_PROBABILITY_GAP.equals(normalized)) {
            return Strategy.FILL_PROBABILITY_GAP;
        }
        return null;
    }

    static String compensationActionTypeForStructuralStrategy(String strategy) {
        String normalized = normalizeStrategy(strategy);
        if (Strategy.REBALANCE_TIER_RATIO.equals(normalized)) {
            return CompensationActionType.REBALANCE_PROTECT_RATIO;
        }
        if (Strategy.FILL_PROBABILITY_GAP.equals(normalized)) {
            return CompensationActionType.FILL_PROBABILITY_GAP;
        }
        return null;
    }

    private static Map<String, String> buildStrategyAliases() {
        Map<String, String> aliases = new LinkedHashMap<String, String>();
        aliases.put("fill_total_count", Strategy.FILL_MISSING_COUNT);
        aliases.put("add_local_protect", Strategy.ADD_SAFETY_ITEMS);
        aliases.put("rebalance_protect_ratio", Strategy.REBALANCE_TIER_RATIO);
        aliases.put("sort_ordered_plan", Strategy.SORT_BY_PROBABILITY);
        aliases.put("remove_volunteers", Strategy.REMOVE_RISK_ITEMS);
        aliases.put("replace_volunteers", Strategy.REPLACE_RISK_ITEMS);
        aliases.put("blocked", Strategy.CANNOT_SATISFY);
        aliases.put("info", Strategy.NO_OP);
        return Collections.unmodifiableMap(aliases);
    }

    private static Map<String, String> buildActionTypeAliases() {
        Map<String, String> aliases = new LinkedHashMap<String, String>();
        aliases.put("sort_ordered_plan", ActionType.REORDER_VOLUNTEERS);
        aliases.put("fill_count", ActionType.FILL_TOTAL_COUNT);
        aliases.put("add_units", ActionType.ADD_VOLUNTEERS);
        aliases.put("remove_units", ActionType.REMOVE_VOLUNTEERS);
        aliases.put("replace_units", ActionType.REPLACE_VOLUNTEERS);
        return Collections.unmodifiableMap(aliases);
    }

    private static Map<String, Set<String>> buildStrategyActionTypes() {
        Map<String, Set<String>> result = new LinkedHashMap<String, Set<String>>();
        result.put(Strategy.FILL_MISSING_COUNT, unmodifiableSet(ActionType.FILL_TOTAL_COUNT));
        result.put(Strategy.ADD_SAFETY_ITEMS, unmodifiableSet(ActionType.ADD_VOLUNTEERS, ActionType.REPLACE_VOLUNTEERS));
        result.put(Strategy.REBALANCE_TIER_RATIO, unmodifiableSet(ActionType.REPLACE_VOLUNTEERS));
        result.put(Strategy.FILL_PROBABILITY_GAP, unmodifiableSet(ActionType.REPLACE_VOLUNTEERS));
        result.put(Strategy.SORT_BY_PROBABILITY, unmodifiableSet(ActionType.REORDER_VOLUNTEERS));
        result.put(Strategy.REMOVE_RISK_ITEMS, unmodifiableSet(ActionType.REMOVE_VOLUNTEERS, ActionType.FILL_TOTAL_COUNT));
        result.put(Strategy.REPLACE_RISK_ITEMS, unmodifiableSet(ActionType.REPLACE_VOLUNTEERS));
        result.put(Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY, unmodifiableSet(ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY));
        result.put(Strategy.ONLY_KEEP_SCOPE, unmodifiableSet(ActionType.REMOVE_VOLUNTEERS, ActionType.ADD_VOLUNTEERS));
        result.put(Strategy.MUST_INCLUDE_SCOPE, unmodifiableSet(ActionType.ADD_VOLUNTEERS, ActionType.REPLACE_VOLUNTEERS));
        result.put(Strategy.EXCLUDE_SCOPE, unmodifiableSet(ActionType.REMOVE_VOLUNTEERS, ActionType.REPLACE_VOLUNTEERS));
        result.put(Strategy.TUITION_BUDGET_SCOPE, unmodifiableSet(ActionType.REMOVE_VOLUNTEERS, ActionType.REPLACE_VOLUNTEERS));
        result.put(Strategy.NO_OP, unmodifiableSet(ActionType.NO_OP));
        result.put(Strategy.CANNOT_SATISFY, unmodifiableSet(ActionType.NO_OP));
        return Collections.unmodifiableMap(result);
    }

    private static Set<String> unmodifiableSet(String... values) {
        return Collections.unmodifiableSet(new LinkedHashSet<String>(Arrays.asList(values)));
    }

    private static String normalizeText(String value) {
        return value == null ? "" : value.trim();
    }
}
