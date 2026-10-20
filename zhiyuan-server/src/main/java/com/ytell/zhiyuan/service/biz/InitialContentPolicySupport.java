package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 初始方案内容护栏的共享口径：风险标签、计划条目数、preferred 专业数。
 *
 * <p>求解前约束（staged solver）与求解后兜底（CanonicalPlanningRuntime）必须
 * 使用同一套识别规则，避免一边放行、一边回退。</p>
 */
final class InitialContentPolicySupport {

    static final String[] RISK_CODES = new String[]{
            "special_enrollment", "cooperative_program", "high_tuition", "admission_limit"};

    private InitialContentPolicySupport() {
    }

    static Set<String> riskTags(CandidateFactDTO fact) {
        Set<String> tags = new LinkedHashSet<String>();
        if (fact == null) {
            return tags;
        }
        List<CandidateItemDTO> raw = fact.getRawCandidates() == null
                ? java.util.Collections.<CandidateItemDTO>emptyList() : fact.getRawCandidates();
        if (raw.isEmpty()) {
            if (fact.getRiskFlags() != null) {
                tags.addAll(fact.getRiskFlags());
            }
            if (fact.getTuitionPerYear() != null && fact.getTuitionPerYear() > 20000) {
                tags.add("high_tuition");
            }
            return tags;
        }
        for (CandidateItemDTO candidate : raw) {
            if (candidate == null) {
                continue;
            }
            if (candidate.getRiskFlags() != null) {
                tags.addAll(candidate.getRiskFlags());
            }
            if (candidate.getReasonCodes() != null) {
                tags.addAll(candidate.getReasonCodes());
            }
            if (candidate.getMustSubjects() != null) {
                tags.addAll(candidate.getMustSubjects());
            }
            String text = Strings.nullToEmpty(candidate.getSchoolName())
                    + Strings.nullToEmpty(candidate.getMajorName());
            if (candidate.getTuitionPerYear() != null
                    && candidate.getTuitionPerYear() > 20000) {
                tags.add("high_tuition");
            }
            if (text.contains("中外合作")) {
                tags.add("cooperative_program");
            }
            if (containsAny(text, "专项", "公费", "定向", "免费医学生", "强基",
                    "国家计划", "地方专项", "高校专项")) {
                tags.add("special_enrollment");
            }
            if (containsAny(text, "色盲", "色弱", "单科", "性别", "语种")) {
                tags.add("admission_limit");
            }
        }
        return tags;
    }

    static boolean hasRisk(Set<String> tags, String code) {
        if ("cooperative_program".equals(code)) {
            return containsTag(tags, "cooperative_program") || containsTag(tags, "cooperative");
        }
        if ("high_tuition".equals(code)) {
            return containsTag(tags, "high_tuition") || containsTag(tags, "high_fee");
        }
        return containsTag(tags, code);
    }

    static Map<String, Integer> riskCounts(List<CandidateFactDTO> facts) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        for (CandidateFactDTO fact : facts == null
                ? java.util.Collections.<CandidateFactDTO>emptyList() : facts) {
            Set<String> tags = riskTags(fact);
            for (String code : RISK_CODES) {
                if (hasRisk(tags, code)) {
                    counts.merge(code, 1, Integer::sum);
                }
            }
        }
        return counts;
    }

    static int itemCount(List<CandidateFactDTO> facts, boolean unitMode) {
        if (!unitMode) {
            return facts == null ? 0 : facts.size();
        }
        int count = 0;
        for (CandidateFactDTO fact : facts == null
                ? java.util.Collections.<CandidateFactDTO>emptyList() : facts) {
            count += Math.max(1, fact.getRawCandidates() == null
                    ? 0 : fact.getRawCandidates().size());
        }
        return count;
    }

    static int itemCount(CandidateFactDTO fact, boolean unitMode) {
        if (!unitMode) {
            return 1;
        }
        return Math.max(1, fact == null || fact.getRawCandidates() == null
                ? 0 : fact.getRawCandidates().size());
    }

    static int preferredCount(List<CandidateFactDTO> facts) {
        Set<String> preferred = new LinkedHashSet<String>();
        for (CandidateFactDTO fact : facts == null
                ? java.util.Collections.<CandidateFactDTO>emptyList() : facts) {
            preferred.addAll(preferredVolunteerIds(fact));
        }
        return preferred.size();
    }

    static Set<String> preferredVolunteerIds(CandidateFactDTO fact) {
        Set<String> preferred = new LinkedHashSet<String>();
        if (fact == null || fact.getRawCandidates() == null) {
            return preferred;
        }
        for (CandidateItemDTO candidate : fact.getRawCandidates()) {
            if (candidate != null && Boolean.TRUE.equals(candidate.getPreferred())
                    && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                preferred.add(candidate.getVolunteerId());
            }
        }
        return preferred;
    }

    static int itemAllowance(int baselineItems) {
        return Math.max(5, (int) Math.ceil(baselineItems * 0.20D));
    }

    private static boolean containsTag(Set<String> tags, String code) {
        for (String tag : tags == null ? new LinkedHashSet<String>() : tags) {
            if (tag != null && tag.toLowerCase().contains(code)) {
                return true;
            }
        }
        return false;
    }

    private static boolean containsAny(String text, String... keywords) {
        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }
}
