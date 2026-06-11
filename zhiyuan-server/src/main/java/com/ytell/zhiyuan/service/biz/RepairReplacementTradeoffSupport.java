package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;

final class RepairReplacementTradeoffSupport {

    private RepairReplacementTradeoffSupport() {
    }

    static int compareTradeoff(CandidateItemDTO leftRemove,
                               CandidateItemDTO leftAdd,
                               CandidateItemDTO rightRemove,
                               CandidateItemDTO rightAdd) {
        int compare = Integer.compare(majorSimilarityLevel(leftRemove, leftAdd),
                majorSimilarityLevel(rightRemove, rightAdd));
        if (compare != 0) {
            return compare;
        }
        compare = Integer.compare(schoolRankDowngradePenalty(leftRemove, leftAdd),
                schoolRankDowngradePenalty(rightRemove, rightAdd));
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(scoreLossPenalty(leftRemove == null ? null : leftRemove.getFinalScore(),
                        leftAdd == null ? null : leftAdd.getFinalScore()),
                scoreLossPenalty(rightRemove == null ? null : rightRemove.getFinalScore(),
                        rightAdd == null ? null : rightAdd.getFinalScore()));
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(scoreLossPenalty(leftRemove == null ? null : leftRemove.getIntentScore(),
                        leftAdd == null ? null : leftAdd.getIntentScore()),
                scoreLossPenalty(rightRemove == null ? null : rightRemove.getIntentScore(),
                        rightAdd == null ? null : rightAdd.getIntentScore()));
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(leftAdd == null ? null : leftAdd.getFinalScore(),
                rightAdd == null ? null : rightAdd.getFinalScore());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(leftAdd == null ? null : leftAdd.getAdmissionRatio(),
                rightAdd == null ? null : rightAdd.getAdmissionRatio());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(leftAdd == null ? null : leftAdd.getIntentScore(),
                rightAdd == null ? null : rightAdd.getIntentScore());
        if (compare != 0) {
            return compare;
        }
        return compareNullableIntegerAsc(leftAdd == null ? null : leftAdd.getSchoolRank(),
                rightAdd == null ? null : rightAdd.getSchoolRank());
    }

    static int majorSimilarityLevel(CandidateItemDTO source, CandidateItemDTO candidate) {
        if (source == null || candidate == null) {
            return 99;
        }
        if (sameNonEmpty(source.getMajorId(), candidate.getMajorId())
                || sameNonEmpty(source.getMajorCode(), candidate.getMajorCode())
                || sameNormalizedMajorName(source.getMajorName(), candidate.getMajorName())) {
            return 0;
        }
        if (sameNonEmpty(source.getMajorSubCategoryId(), candidate.getMajorSubCategoryId())) {
            return 1;
        }
        if (sameNonEmpty(source.getMajorCategoryId(), candidate.getMajorCategoryId())
                || sameNonEmpty(source.getMajorCategory(), candidate.getMajorCategory())) {
            return 2;
        }
        if (sameNonEmpty(source.getMajorDiscipline(), candidate.getMajorDiscipline())) {
            return 3;
        }
        return 99;
    }

    static int schoolRankDowngradePenalty(CandidateItemDTO source, CandidateItemDTO candidate) {
        Integer sourceRank = source == null ? null : source.getSchoolRank();
        Integer candidateRank = candidate == null ? null : candidate.getSchoolRank();
        if (sourceRank == null || sourceRank <= 0 || candidateRank == null || candidateRank <= 0) {
            return 0;
        }
        return Math.max(0, candidateRank - sourceRank);
    }

    static double scoreLossPenalty(Double sourceValue, Double candidateValue) {
        if (sourceValue == null || candidateValue == null) {
            return 0D;
        }
        return Math.max(0D, sourceValue - candidateValue);
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

    private static boolean sameNonEmpty(String left, String right) {
        if (Strings.isNullOrEmpty(left) || Strings.isNullOrEmpty(right)) {
            return false;
        }
        return left.trim().equals(right.trim());
    }

    private static boolean sameNormalizedMajorName(String left, String right) {
        String normalizedLeft = normalizeMajorName(left);
        String normalizedRight = normalizeMajorName(right);
        return !Strings.isNullOrEmpty(normalizedLeft) && normalizedLeft.equals(normalizedRight);
    }

    private static String normalizeMajorName(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return "";
        }
        return value
                .replaceAll("（.*?）", "")
                .replaceAll("\\(.*?\\)", "")
                .replaceAll("\\s+", "")
                .trim();
    }
}
