package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.manager.MajorProfileManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.MajorProfileDto;
import com.ytell.zhiyuan.model.dto.inner.MajorSubjectAvailReq;
import com.ytell.zhiyuan.model.dto.inner.PlanParamAvailReq;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerMajor;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 志愿方案验证服务
 */
@Slf4j
@Service
public class PlanValidationService {
    @Autowired
    private ChatSessionBizService chatSessionBizService;

    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;

    @Autowired
    private MajorProfileManager majorProfileManager;


    /**
     * 根据全量方案判断学生的志愿诉求能否满足
     *
     * @param tenantId 租户ID
     * @param req      请求参数
     * @return 是否满足
     */
    public boolean checkPlanParamAvailability(Long tenantId, PlanParamAvailReq req) {
        log.info("checkPlanParamAvailability: tenantId={}, req={}", tenantId, JSONObject.toJSONString(req));

        List<VolunteerSchoolGroup> volunteerSchoolGroups = chatSessionBizService.loadSessionVolunteerFormatData(Long.valueOf(req.getChatSessionId()));

        if (volunteerSchoolGroups == null || volunteerSchoolGroups.isEmpty()) {
            log.warn("志愿方案数据为空，无法满足参数要求");
            return false;
        }

        // 检查majors参数（内部OR关系）
        boolean majorsMatched = checkMajorsAvailability(volunteerSchoolGroups, req.getMajors());

        // 检查schools参数（内部OR关系）
        boolean schoolsMatched = checkSchoolsAvailability(volunteerSchoolGroups, req.getSchools());

        // 检查locations参数（内部OR关系）
        boolean locationsMatched = checkLocationsAvailability(volunteerSchoolGroups, req.getLocations());

        // 三个部分之间是AND关系
        boolean result = majorsMatched && schoolsMatched && locationsMatched;

        log.info("参数匹配结果: majors={}, schools={}, locations={}, 最终结果={}",
                majorsMatched, schoolsMatched, locationsMatched, result);

        return result;
    }

    /**
     * 根据学生选课判断能否填报相关专业
     *
     * @param tenantId 租户ID
     * @param req      请求参数
     * @return 是否满足
     */
    public boolean checkMajorSubjectAvailability(Long tenantId, MajorSubjectAvailReq req) {
        log.info("checkMajorSubjectAvailability: tenantId={}, req={}", tenantId, JSONObject.toJSONString(req));

        ChatSessionExtraData userScore = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(Long.valueOf(req.getChatSessionId()), ChatSessionExtraDataConstants.USER_SCORE_KEY);
        CreateSessionReq memberScoreDetailDTO = JSONObject.parseObject(userScore.getDataValue(), CreateSessionReq.class);

        // 获取学生选的科目列表
        List<String> studentSubjects = getStudentSubjects(memberScoreDetailDTO);
        log.info("学生选择的科目: {}", studentSubjects);

        List<String> majors = req.getMajors().getOrDefault("level3", new ArrayList<>());

        // 检查每个专业的选科要求
        for (String majorId : majors) {
            MajorProfileDto majorProfile = majorProfileManager.getMajorProfileById(majorId);
            if (majorProfile == null) {
                log.warn("专业代码 {} 对应的专业信息不存在", majorId);
                return false;
            }

            List<List<String>> selectLimit = majorProfile.getSelectLimit();

            // 检查学生选科是否满足该专业要求
            if (!checkSubjectRequirement(studentSubjects, selectLimit, majorId)) {
                log.info("专业 {} ({}) 选科要求不满足", majorId, majorProfile.getName());
                return false;
            }
        }

        log.info("所有专业的选科要求都满足");
        return true;
    }

    /**
     * 检查专业参数是否匹配
     * majors.level2中的参数对应volunteerSchoolGroups[n].majorList[m].subCategoryId
     * majors.level3中的参数对应volunteerSchoolGroups[n].majorList[m].majorId
     *
     * @param volunteerSchoolGroups 志愿方案数据
     * @param majors                专业参数映射
     * @return 是否匹配
     */
    private boolean checkMajorsAvailability(List<VolunteerSchoolGroup> volunteerSchoolGroups, Map<String, List<String>> majors) {
        if (majors == null || majors.isEmpty()) {
            // 如果没有专业要求，则认为满足
            return true;
        }

        List<String> level2Majors = majors.get("level2");
        List<String> level3Majors = majors.get("level3");

        // 如果level2和level3都为空，则认为满足
        if ((level2Majors == null || level2Majors.isEmpty()) &&
                (level3Majors == null || level3Majors.isEmpty())) {
            return true;
        }

        // 遍历所有志愿方案数据
        for (VolunteerSchoolGroup schoolGroup : volunteerSchoolGroups) {
            if (schoolGroup.getMajorList() == null || schoolGroup.getMajorList().isEmpty()) {
                continue;
            }

            // 检查当前学校专业组是否匹配
            for (VolunteerMajor major : schoolGroup.getMajorList()) {
                // 检查level2专业（二级分类）
                if (level2Majors != null && !level2Majors.isEmpty()) {
                    if (major.getSubCategoryId() != null && level2Majors.contains(major.getSubCategoryId())) {
                        return true;
                    }
                }

                // 检查level3专业（具体专业）
                if (level3Majors != null && !level3Majors.isEmpty()) {
                    if (major.getMajorId() != null && level3Majors.contains(major.getMajorId())) {
                        return true;
                    }
                }
            }
        }

        return false;
    }

    /**
     * 检查学校参数是否匹配
     * schools中的参数对应volunteerSchoolGroups[n].schoolId
     *
     * @param volunteerSchoolGroups 志愿方案数据
     * @param schools               学校参数列表
     * @return 是否匹配
     */
    private boolean checkSchoolsAvailability(List<VolunteerSchoolGroup> volunteerSchoolGroups, List<String> schools) {
        if (schools == null || schools.isEmpty()) {
            // 如果没有学校要求，则认为满足
            return true;
        }

        // 遍历所有志愿方案数据，检查是否有匹配的学校
        for (VolunteerSchoolGroup schoolGroup : volunteerSchoolGroups) {
            if (schoolGroup.getSchoolId() != null && schools.contains(schoolGroup.getSchoolId())) {
                return true;
            }
        }

        return false;
    }

    /**
     * 检查地域参数是否匹配
     * locations.province中的参数对应volunteerSchoolGroups[n].provinceId
     * locations.city中的参数对应volunteerSchoolGroups[n].cityId
     *
     * @param volunteerSchoolGroups 志愿方案数据
     * @param locations             地域参数
     * @return 是否匹配
     */
    private boolean checkLocationsAvailability(List<VolunteerSchoolGroup> volunteerSchoolGroups, PlanParamAvailReq.LocationInfo locations) {
        if (locations == null) {
            // 如果没有地域要求，则认为满足
            return true;
        }

        List<String> provinces = locations.getProvince();
        List<String> cities = locations.getCity();

        // 如果省份和城市都为空，则认为满足
        if ((provinces == null || provinces.isEmpty()) &&
                (cities == null || cities.isEmpty())) {
            return true;
        }

        // 遍历所有志愿方案数据
        for (VolunteerSchoolGroup schoolGroup : volunteerSchoolGroups) {
            // 检查省份匹配
            if (provinces != null && !provinces.isEmpty()) {
                if (schoolGroup.getProvinceId() != null && provinces.contains(schoolGroup.getProvinceId())) {
                    return true;
                }
            }

            // 检查城市匹配
            if (cities != null && !cities.isEmpty()) {
                if (schoolGroup.getCityId() != null && cities.contains(schoolGroup.getCityId())) {
                    return true;
                }
            }
        }

        return false;
    }

    /**
     * 从用户信息中提取学生选择的科目列表
     *
     * @param createSessionReq 用户会话创建请求
     * @return 学生选择的科目名称列表
     */
    private List<String> getStudentSubjects(CreateSessionReq createSessionReq) {
        List<String> subjects = new ArrayList<>();

        if (createSessionReq == null || createSessionReq.getSubjectList() == null) {
            log.warn("用户选科信息为空");
            return subjects;
        }

        for (CreateSessionReq.SubjectItem subjectItem : createSessionReq.getSubjectList()) {
            if (subjectItem.getName() != null && !subjectItem.getName().trim().isEmpty()) {
                subjects.add(subjectItem.getName().trim());
            }
        }

        return subjects;
    }

    /**
     * 检查学生选科是否满足专业要求
     *
     * @param studentSubjects 学生选择的科目列表
     * @param selectLimit     专业选科限制（二维列表，每个内层列表表示一种选科组合）
     * @param majorCode       专业代码（用于日志）
     * @return 是否满足要求
     */
    private boolean checkSubjectRequirement(List<String> studentSubjects, List<List<String>> selectLimit, String majorCode) {
        // 如果专业没有选科限制（selectLimit为空），则认为满足
        if (selectLimit == null || selectLimit.isEmpty()) {
            log.debug("专业 {} 没有选科限制", majorCode);
            return true;
        }

        // 检查学生选科是否满足任意一种选科组合
        for (int i = 0; i < selectLimit.size(); i++) {
            List<String> requiredCombination = selectLimit.get(i);
            if (checkSingleCombination(studentSubjects, requiredCombination)) {
                log.debug("专业 {} 的第{}种选科组合满足: {}", majorCode, i + 1, requiredCombination);
                return true;
            }
        }

        log.info("专业 {} 的所有选科组合都不满足。要求: {}, 学生选科: {}", majorCode, selectLimit, studentSubjects);
        return false;
    }

    /**
     * 检查学生选科是否满足单个选科组合
     *
     * @param studentSubjects     学生选择的科目列表
     * @param requiredCombination 要求的选科组合
     * @return 是否满足该组合
     */
    private boolean checkSingleCombination(List<String> studentSubjects, List<String> requiredCombination) {
        if (requiredCombination == null || requiredCombination.isEmpty()) {
            return true;
        }

        // 学生必须选择了该组合中的所有科目
        for (String requiredSubject : requiredCombination) {
            if (!studentSubjects.contains(requiredSubject)) {
                return false;
            }
        }

        return true;
    }

}
