package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.util.ApplyTypeUtil;
import com.ytell.zhiyuan.manager.rank.VolunteerRankClient;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendVolunteerRequest;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerMajor;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.stream.Collectors;

/**
 * 志愿排序器和合并
 * 负责对志愿数据进行各种排序处理
 */
@Slf4j
@Component
public class VolunteerSorterAndMerger {

    @Autowired
    private VolunteerIntervalService volunteerIntervalService;

    @Autowired
    private VolunteerRankClient volunteerRankClient;

    @Autowired
    private VolunteerRequestExecutorManager executorManager;


    /**
     * 对志愿列表进行分区间排序和截断
     *
     * @param volunteerData        志愿数据
     * @param userScoreDetail      用户分数信息
     * @param userFinalProfileData 用户合并后画像
     * @param applyType            填报类型
     * @param split                是否截断
     * @param threeTargetCountMap  冲稳保三大区间的目标数
     * @return 排序后的区间数据
     */
    public Map<String, List<VolunteerSchoolGroup>> sortAndSplitByInterval(List<VolunteerSchoolGroup> volunteerData,
                                                                          CreateSessionReq userScoreDetail,
                                                                          UserProfileData userFinalProfileData,
                                                                          String applyType,
                                                                          Boolean split,
                                                                          Map<String, Integer> threeTargetCountMap) {

        // 1. 九宫格细分逻辑，按照冲稳保三区间[每个区间又三个区间]进行切分
        Map<String, List<VolunteerSchoolGroup>> volunteerIntervalMap = volunteerIntervalService.divideVolunteers(volunteerData, true);
        log.info("dividedIntervalData:size:{}", volunteerIntervalMap.size());

        // 2. 对九宫格各个区间进行排序
        Map<String, List<VolunteerSchoolGroup>> sortedIntervalData = this.sortEveryInterval(volunteerIntervalMap, userScoreDetail, userFinalProfileData);
        log.info("sortedIntervalData:size:{}", sortedIntervalData.size());

        // 3. 需要进行九宫格合并成三宫格（水位线前进行录取率排序、可能截断）
        Map<String, List<VolunteerSchoolGroup>> mergedIntervalData = this.mergeToThreeInterval(sortedIntervalData,userScoreDetail, threeTargetCountMap, split);
        log.info("mergedIntervalData:size:{}", mergedIntervalData.size());

        // 4. 如果是专业组模式，还要对专业组里的专业进行截断
        if (!ApplyTypeUtil.isMajorSchoolType(applyType)) {
            // 专业的目标数量；成绩行缺 volunteerCount（老会话/legacy 草稿未补录）时拿不到目标数，
            // 跳过专业列表截断（全量保留），不再 NPE 成 code -1。
            Integer targetMajorCount = userScoreDetail == null || userScoreDetail.getVolunteerCount() == null
                    ? null : userScoreDetail.getVolunteerCount().getMajorCount();
            if (targetMajorCount == null) {
                log.warn("sortAndSplitByInterval skip major truncation reason=volunteer_count_missing");
            } else {
                // 遍历进行专业列表截断
                mergedIntervalData.entrySet().forEach(kv -> {
                    List<VolunteerSchoolGroup> sortedSchoolGroups = kv.getValue();
                    sortedSchoolGroups.forEach(group -> {
                        // 对专业进行截断
                        processTruncatedMajorList(group, targetMajorCount, split);
                    });
                });
            }
        }

        return mergedIntervalData;
    }

    /**
     * 对每个区间进行排序
     */
    private Map<String, List<VolunteerSchoolGroup>> sortEveryInterval(Map<String, List<VolunteerSchoolGroup>> intervalResult, CreateSessionReq userScoreDetail, UserProfileData userFinalProfileData) {

        log.info("开始并发排序区间数据，区间数量: {}", intervalResult.size());

        // 获取线程池实例
        ExecutorService executor = executorManager.getExecutor();

        // 等待所有请求完成并收集结果
        Map<String, List<VolunteerSchoolGroup>> sorted = new java.util.HashMap<>(intervalResult.size());

        try {
            // 创建所有请求的CompletableFuture列表
            List<CompletableFuture<Map.Entry<String, List<VolunteerSchoolGroup>>>> futures = intervalResult.entrySet().stream()
                .filter(entry -> !VolunteerIntervalService.UNKNOWN_INTERVAL.equals(entry.getKey()))
                .map(entry -> CompletableFuture.<Map.Entry<String, List<VolunteerSchoolGroup>>>supplyAsync(() -> {
                    String intervalType = entry.getKey();
                    List<VolunteerSchoolGroup> subGroups = entry.getValue();

                    try {
                        log.info("开始排序区间: {}", intervalType);
                        if(subGroups.isEmpty()){
                            log.info("数据为空，直接返回: {}", intervalType);
                            return new AbstractMap.SimpleEntry<>(intervalType, subGroups);
                        }
                        RecommendVolunteerRequest sortRequest = new RecommendVolunteerRequest();
                        sortRequest.setStudentinfo(userScoreDetail);
                        sortRequest.setVolunteerinfo(subGroups);
                        sortRequest.setProfileinfo(userFinalProfileData);
                        List<VolunteerSchoolGroup> afterSorted = volunteerRankClient.getRecommendVolunteer(sortRequest);
                        log.info("完成排序区间: {}, 结果数量: {}", intervalType, afterSorted != null ? afterSorted.size() : 0);

                        return new AbstractMap.SimpleEntry<>(intervalType, afterSorted);
                    } catch (Exception e) {
                        log.error("排序区间 {} 失败", intervalType, e);
                        throw new RuntimeException("排序区间 " + intervalType + " 失败", e);
                    }
                }, executor))
                .collect(Collectors.toList());

            try {
                CompletableFuture.allOf(futures.toArray(new CompletableFuture[0]))
                    .get(); // 等待所有任务完成

                // 收集结果
                for (CompletableFuture<Map.Entry<String, List<VolunteerSchoolGroup>>> future : futures) {
                    Map.Entry<String, List<VolunteerSchoolGroup>> result = future.get();
                    sorted.put(result.getKey(), result.getValue());
                }
            } catch (InterruptedException | ExecutionException e) {
                log.error("并发排序过程中发生异常", e);
                throw new RuntimeException("并发排序过程中发生异常", e);
            }
        } catch (Exception e) {
            log.error("并发排序过程中发生异常", e);
            throw e;
        }

        log.info("完成并发排序区间数据，结果区间数量: {}", sorted.size());
        return sorted;
    }


    /**
     * 合并为三个区间
     */
    private Map<String, List<VolunteerSchoolGroup>> mergeToThreeInterval(Map<String, List<VolunteerSchoolGroup>> volunteerIntervalMap,
                                                                         CreateSessionReq userScoreDetail,
                                                                         Map<String, Integer> threeTargetCountMap,
                                                                         boolean split) {
        Map<String, List<VolunteerSchoolGroup>> result = new java.util.HashMap<>();

        // 使用通用方法处理冲、稳、保三个区间
        List<VolunteerSchoolGroup> sprintList = mergeIntervalSubGroups(volunteerIntervalMap, userScoreDetail,"冲", threeTargetCountMap.get("冲"), split);
        result.put("冲", sprintList);

        List<VolunteerSchoolGroup> safeList = mergeIntervalSubGroups(volunteerIntervalMap, userScoreDetail,"稳", threeTargetCountMap.get("稳"), split);
        result.put("稳", safeList);

        List<VolunteerSchoolGroup> protectList = mergeIntervalSubGroups(volunteerIntervalMap, userScoreDetail,"保", threeTargetCountMap.get("保"), split);
        result.put("保", protectList);

        return result;
    }


    /**
     * 保3区间的特殊排序逻辑：优先取本省学校
     *
     * @param subGroup3                  保3区间的学校专业组列表
     * @param userScoreDetail            用户分数详情
     * @return 排序后的保3区间学校专业组列表
     */
    private List<VolunteerSchoolGroup> sortProtect3VolunteerData(
            List<VolunteerSchoolGroup> subGroup3,
            CreateSessionReq userScoreDetail) {

        if (subGroup3 == null || subGroup3.isEmpty()) {
            return subGroup3;
        }

        // 获取用户高考省份ID
        String userProvinceId = null;
        if (userScoreDetail != null && userScoreDetail.getProvince() != null) {
            userProvinceId = userScoreDetail.getProvince().getCode();
        }

        // 分离本省和外省学校
        List<VolunteerSchoolGroup> sameProvinceSchools = new ArrayList<>();
        List<VolunteerSchoolGroup> differentProvinceSchools = new ArrayList<>();

        for (VolunteerSchoolGroup schoolGroup : subGroup3) {
            if (userProvinceId != null && userProvinceId.equals(schoolGroup.getProvinceId())) {
                sameProvinceSchools.add(schoolGroup);
            } else {
                differentProvinceSchools.add(schoolGroup);
            }
        }
        // 合并结果：本省学校在前，外省学校在后
        List<VolunteerSchoolGroup> result = new ArrayList<>();
        result.addAll(sameProvinceSchools);
        result.addAll(differentProvinceSchools);
        return result;
    }


    /**
     * 通用的区间轮询合并方法
     * 从多个子区间列表中轮流取元素，直到达到目标数量
     *
     * @param intervalResult 区间结果对象
     * @param  userScoreDetail 用户分数基础信息
     * @param intervalType   区间类型（如"冲"、"稳"、"保"）
     * @param targetCount    目标数量
     * @param split          是否截断
     * @return 合并后的区间数据列表
     */
    private List<VolunteerSchoolGroup> mergeIntervalSubGroups(Map<String, List<VolunteerSchoolGroup>> intervalResult,
                                                              CreateSessionReq userScoreDetail,
                                                              String intervalType,
                                                              Integer targetCount,
                                                              boolean split) {
        List<VolunteerSchoolGroup> mergedList = Lists.newArrayList();
        // 获取子区间数据并排序
        List<VolunteerSchoolGroup> subGroup1 = intervalResult.get(intervalType + "1");
        List<VolunteerSchoolGroup> subGroup2 = intervalResult.get(intervalType + "2");
        List<VolunteerSchoolGroup> subGroup3 = intervalResult.get(intervalType + "3");

        if("保".equals(intervalType)){
            //保3需要特殊处理
            subGroup3= this.sortProtect3VolunteerData(subGroup3,userScoreDetail);

        }

        // 轮询合并逻辑 - 先取目标个数（主列表）
        int index1 = 0, index2 = 0, index3 = 0;
        while (mergedList.size() < targetCount && (index1 < (subGroup1 != null ? subGroup1.size() : 0) || index2 < (subGroup2 != null ? subGroup2.size() : 0) || index3 < (subGroup3 != null ? subGroup3.size() : 0))) {

            // 轮流从三个子区间列表中取元素
            if (subGroup1 != null && index1 < subGroup1.size()) {
                mergedList.add(subGroup1.get(index1++));
                if (mergedList.size() >= targetCount) {
                    break;
                }
            }
            if (subGroup2 != null && index2 < subGroup2.size()) {
                mergedList.add(subGroup2.get(index2++));
                if (mergedList.size() >= targetCount) {
                    break;
                }
            }
            if (subGroup3 != null && index3 < subGroup3.size()) {
                mergedList.add(subGroup3.get(index3++));
                if (mergedList.size() >= targetCount) {
                    break;
                }
            }
        }

        // 水位线之前-按照录取率排序-升序
        mergedList = mergedList.stream().sorted(Comparator.comparing(VolunteerSchoolGroup::getSchoolEnrollRatio)).collect(Collectors.toList());

        if (!split) {
            // 如果不切断，则剩余的也返回
            while (subGroup1 != null && index1 < subGroup1.size()) {
                mergedList.add(subGroup1.get(index1++));
            }
            while (subGroup2 != null && index2 < subGroup2.size()) {
                mergedList.add(subGroup2.get(index2++));
            }
            while (subGroup3 != null && index3 < subGroup3.size()) {
                mergedList.add(subGroup3.get(index3++));
            }
        } else {
            // 如果切断，需要额外保留15个候补志愿
            int backupCount = 15; // 候补志愿数量
            int currentBackupCount = 0;
            List<VolunteerSchoolGroup> backupList = new ArrayList<>();
            
            while (currentBackupCount < backupCount && (index1 < (subGroup1 != null ? subGroup1.size() : 0) || index2 < (subGroup2 != null ? subGroup2.size() : 0) || index3 < (subGroup3 != null ? subGroup3.size() : 0))) {
                // 轮流从三个子区间列表中取候补元素
                if (subGroup1 != null && index1 < subGroup1.size()) {
                    backupList.add(subGroup1.get(index1++));
                    currentBackupCount++;
                    if (currentBackupCount >= backupCount) {
                        break;
                    }
                }
                if (subGroup2 != null && index2 < subGroup2.size()) {
                    backupList.add(subGroup2.get(index2++));
                    currentBackupCount++;
                    if (currentBackupCount >= backupCount) {
                        break;
                    }
                }
                if (subGroup3 != null && index3 < subGroup3.size()) {
                    backupList.add(subGroup3.get(index3++));
                    currentBackupCount++;
                    if (currentBackupCount >= backupCount) {
                        break;
                    }
                }
            }
            
            // 对候补列表按照录取率排序-升序
            if (!backupList.isEmpty()) {
                backupList = backupList.stream().sorted(Comparator.comparing(VolunteerSchoolGroup::getSchoolEnrollRatio)).collect(Collectors.toList());
                mergedList.addAll(backupList);
            }
        }

        return mergedList;
    }

    /**
     * 对专业列表进行截断处理
     *
     * @param volunteerSchoolGroup 志愿学校组
     * @param targetMajorCount     目标专业数量
     * @param split                是否截断
     */
    private void processTruncatedMajorList(VolunteerSchoolGroup volunteerSchoolGroup, Integer targetMajorCount, boolean split) {
        List<VolunteerMajor> majorList = volunteerSchoolGroup.getMajorList();
        if (majorList == null || targetMajorCount == null) {
            return;
        }

        // 专业数量不足或刚好满足目标，无需额外处理
        if (majorList.size() <= targetMajorCount) {
            return;
        }

        List<VolunteerMajor> prioritizedMajors = new java.util.ArrayList<>(majorList.subList(0, targetMajorCount));

        // 截取后是否满足，专业列表里至少有一个最低录取率不小于专业组录取率
        boolean hasHighestMajor = prioritizedMajors.stream()
            .anyMatch(one -> one.getMajorEnrollRatio() >= volunteerSchoolGroup.getSchoolEnrollRatio());

        if (!hasHighestMajor) {
            // 找寻一个录取率不小于专业组录取率的替换
            VolunteerMajor addHighestMajor = majorList.stream()
                .filter(one -> one.getMajorEnrollRatio() >= volunteerSchoolGroup.getSchoolEnrollRatio())
                .findFirst()
                .orElse(null);

            if (addHighestMajor != null) {
                // 替换最后一个为录取率高的
                prioritizedMajors.remove(prioritizedMajors.size() - 1);
                prioritizedMajors.add(addHighestMajor);
            }
        }

        if (split) {
            volunteerSchoolGroup.setMajorList(prioritizedMajors);
            return;
        }

        List<VolunteerMajor> remainingMajors = buildRemainingMajors(majorList, prioritizedMajors);
        List<VolunteerMajor> mergedMajorList = new java.util.ArrayList<>(majorList.size());
        mergedMajorList.addAll(prioritizedMajors);
        mergedMajorList.addAll(remainingMajors);
        volunteerSchoolGroup.setMajorList(mergedMajorList);
    }

    private List<VolunteerMajor> buildRemainingMajors(List<VolunteerMajor> original, List<VolunteerMajor> prioritized) {
        Map<String, Integer> usageMap = new HashMap<>();
        prioritized.forEach(major -> usageMap.merge(major.getMajorId(), 1, Integer::sum));

        List<VolunteerMajor> remaining = new ArrayList<>();
        for (VolunteerMajor major : original) {
            Integer count = usageMap.get(major.getMajorId());
            if (count == null) {
                remaining.add(major);
                continue;
            }

            if (count == 1) {
                usageMap.remove(major.getMajorId());
            } else {
                usageMap.put(major.getMajorId(), count - 1);
            }
        }
        return remaining;
    }
}
