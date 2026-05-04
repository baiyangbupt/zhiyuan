package com.ytell.zhiyuan.service.volunteer;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 志愿区间划分服务
 */
@Slf4j
@Service
public class VolunteerIntervalService {

    /**
     * 区间划分主方法
     * 基于院校录取率进行区间划分，以planSchoolDataId作为院校唯一标识
     */
    public Map<String, List<VolunteerSchoolGroup>> divideVolunteers(
            List<VolunteerSchoolGroup> schoolGroups,
            boolean useNineIntervals) {
        // 1. 按院校录取率排序
        schoolGroups.sort((a, b) -> {
            Double ratioA = a.getSchoolEnrollRatio() != null ? a.getSchoolEnrollRatio() : 0.0;
            Double ratioB = b.getSchoolEnrollRatio() != null ? b.getSchoolEnrollRatio() : 0.0;
            return Double.compare(ratioA, ratioB); // 升序排列
        });
        // 2. 按院校录取率分配到区间-
        Map<String, List<VolunteerSchoolGroup>> intervals = assignToIntervals(schoolGroups, useNineIntervals);
        return intervals;
    }

    /**
     * 按院校录取率分配到区间
     */
    private Map<String, List<VolunteerSchoolGroup>> assignToIntervals(List<VolunteerSchoolGroup> schoolGroups, boolean useNineIntervals) {
        Map<String, List<VolunteerSchoolGroup>> intervals = new HashMap<>();

        if (useNineIntervals) {
            // 初始化9个小区间
            String[] intervalNames = {"冲1", "冲2", "冲3", "稳1", "稳2", "稳3", "保1", "保2", "保3"};
            for (String name : intervalNames) {
                intervals.put(name, new ArrayList<>());
            }

            // 按院校录取率分配到9个小区间
            for (VolunteerSchoolGroup schoolGroup : schoolGroups) {
                Double ratio = schoolGroup.getSchoolEnrollRatio();
                if (ratio == null) {
                    intervals.get("保3").add(schoolGroup); // 默认放到保3
                    continue;
                }

                if (ratio >= 1 && ratio <= 10) {
                    intervals.get("冲1").add(schoolGroup);
                } else if (ratio >= 11 && ratio <= 34) {
                    intervals.get("冲2").add(schoolGroup);
                } else if (ratio >= 35 && ratio <= 50) {
                    intervals.get("冲3").add(schoolGroup);
                } else if (ratio >= 51 && ratio <= 56) {
                    intervals.get("稳1").add(schoolGroup);
                } else if (ratio >= 57 && ratio <= 62) {
                    intervals.get("稳2").add(schoolGroup);
                } else if (ratio >= 63 && ratio <= 70) {
                    intervals.get("稳3").add(schoolGroup);
                } else if (ratio >= 71 && ratio <= 86) {
                    intervals.get("保1").add(schoolGroup);
                } else if (ratio >= 87 && ratio <= 98) {
                    intervals.get("保2").add(schoolGroup);
                } else if (ratio >= 99 && ratio <= 100) {
                    intervals.get("保3").add(schoolGroup);
                } else {
                    intervals.get("保3").add(schoolGroup); // 默认放到保3
                }
            }
        } else {
            // 初始化3个大区间
            String[] intervalNames = {"冲", "稳", "保"};
            for (String name : intervalNames) {
                intervals.put(name, new ArrayList<>());
            }

            // 按院校录取率分配到3个大区间
            for (VolunteerSchoolGroup schoolGroup : schoolGroups) {
                Double ratio = schoolGroup.getSchoolEnrollRatio();
                if (ratio == null) {
                    intervals.get("保").add(schoolGroup); // 默认放到保
                    continue;
                }

                if (ratio >= 1 && ratio <= 50) {
                    intervals.get("冲").add(schoolGroup);
                } else if (ratio >= 51 && ratio <= 70) {
                    intervals.get("稳").add(schoolGroup);
                } else if (ratio >= 71 && ratio <= 100) {
                    intervals.get("保").add(schoolGroup);
                } else {
                    intervals.get("保").add(schoolGroup); // 默认放到保
                }
            }
        }

        return intervals;
    }



    /**
     * 计算目标数量分布
     */
    public Map<String, Integer> calculateTargetCounts(int totalCount, boolean useNineIntervals, CreateSessionReq.StrategyType strategyType) {
        Map<String, Integer> result = new HashMap<>();

        // 根据strategyType获取冲稳保比例
        double rushRatio = 0.3;  // 默认冲比例
        double stableRatio = 0.4; // 默认稳比例
        double safeRatio = 0.3;   // 默认保比例

        if (strategyType != null && strategyType.getCode() != null) {
            String code = strategyType.getCode();
            if ("aggressive".equals(code)) {
                // 激进型：冲稳保 = 4:3:3
                rushRatio = 0.4;
                stableRatio = 0.3;
                safeRatio = 0.3;
            } else if ("cautious".equals(code)) {
                // 稳妥型：冲稳保 = 3:3:4
                rushRatio = 0.3;
                stableRatio = 0.3;
                safeRatio = 0.4;
            } else if ("traditional".equals(code)) {
                // 保守型：冲稳保 = 2:4:4
                rushRatio = 0.2;
                stableRatio = 0.4;
                safeRatio = 0.4;
            }
        }

        if (useNineIntervals) {
            // 9个小区间分布，在大区间比例基础上细分
            result.put("冲1", (int) (totalCount * rushRatio * 0.2)); // 冲比例 * 20%
            result.put("冲2", (int) (totalCount * rushRatio * 0.48)); // 冲比例 * 48%
            result.put("冲3", (int) (totalCount * rushRatio * 0.32)); // 冲比例 * 32%
            result.put("稳1", (int) (totalCount * stableRatio * 0.3)); // 稳比例 * 30%
            result.put("稳2", (int) (totalCount * stableRatio * 0.3)); // 稳比例 * 30%
            result.put("稳3", (int) (totalCount * stableRatio * 0.4)); // 稳比例 * 40%
            result.put("保1", (int) (totalCount * safeRatio * 0.533)); // 保比例 * 53.3%
            result.put("保2", (int) (totalCount * safeRatio * 0.4)); // 保比例 * 40%

            // 计算前面8个区间的总和
            int sum = result.values().stream().mapToInt(Integer::intValue).sum();
            // 最后一个区间用总数减去其他区间总和，确保总数匹配
            result.put("保3", totalCount - sum);
        } else {
            // 3个大区间分布
            result.put("冲", (int) (totalCount * rushRatio));
            result.put("稳", (int) (totalCount * stableRatio));

            // 计算前面2个区间的总和
            int sum = result.values().stream().mapToInt(Integer::intValue).sum();
            // 最后一个区间用总数减去其他区间总和，确保总数匹配
            result.put("保", totalCount - sum);
        }

        return result;
    }
}
