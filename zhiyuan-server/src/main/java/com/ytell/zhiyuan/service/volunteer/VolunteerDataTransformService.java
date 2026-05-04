package com.ytell.zhiyuan.service.volunteer;

import com.ytell.zhiyuan.common.util.ApplyTypeUtil;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import com.ytell.zhiyuan.model.dto.volunteer.HistoryRecordDTO;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerMajor;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 志愿数据转换服务
 */
@Slf4j
@Service
public class VolunteerDataTransformService {

    @Autowired
    private SchoolManager schoolManager;

    /**
     * 将ProgramPageDTO.SchoolDetail转换为统一的VolunteerSchoolGroup列表
     * 以planSchoolDataId作为院校唯一标识
     */
    public List<VolunteerSchoolGroup> transformToVolunteerSchoolGroups(List<ProgramPageDTO.SchoolDetail> schoolDetails, String applyType) {
        // 按planSchoolDataId分组
        Map<String, VolunteerSchoolGroup> schoolGroupMap = new HashMap<>();

        for (ProgramPageDTO.SchoolDetail schoolDetail : schoolDetails) {
            String planSchoolDataId = schoolDetail.getPlanSchoolDataId();

            // 检查planSchoolDataId是否为空
            if (planSchoolDataId == null || planSchoolDataId.trim().isEmpty()) {
                log.warn("发现planSchoolDataId为空的SchoolDetail，跳过处理: schoolId={}, schoolName={}",
                        schoolDetail.getSchoolId(), schoolDetail.getSchoolUnitName());
                continue;
            }

            // 获取或创建院校专业组
            VolunteerSchoolGroup schoolGroup = schoolGroupMap.computeIfAbsent(planSchoolDataId, k -> {
                VolunteerSchoolGroup group = new VolunteerSchoolGroup();
                group.setPlanSchoolDataId(planSchoolDataId);
                group.setSchoolId(schoolDetail.getSchoolId());
                group.setSchoolName(schoolDetail.getSchoolUnitName());
                group.setSchoolUnitCode(schoolDetail.getSchoolUnitCode());
                group.setMajorList(new ArrayList<>());
                //设置学校历史录取数据（转换为简化结构）
                group.setHistoryRecords(convertSubVOListToHistoryRecords(schoolDetail.getSubVOList()));
                // 设置院校录取信息
                group.setSchoolEnrollRatio(parseEnrollRatio(schoolDetail.getEnrollRatio()));
                group.setSchoolEnrollRatioStr(schoolDetail.getEnrollRatio());
                group.setSchoolVolunteerLevel(schoolDetail.getVolunteerLevel() != null ? schoolDetail.getVolunteerLevel().getCode() : null);

                // 设置院校排名信息（从SchoolManager获取）
                SchoolVO schoolVO = schoolManager.getSchoolById(schoolDetail.getSchoolId());
                if (schoolVO != null && schoolVO.getSchoolRank() != null) {
                    group.setSchoolRank(schoolVO.getSchoolRank());
                }

                // 设置地理位置信息（直接从SchoolDetail获取）
                if (schoolDetail.getArea() != null) {
                    group.setProvinceName(schoolDetail.getArea().getData());
                    group.setProvinceId(schoolDetail.getArea().getKey());
                }
                if (schoolDetail.getCity() != null) {
                    group.setCityName(schoolDetail.getCity().getData());
                    group.setCityId(schoolDetail.getCity().getKey());
                }

                return group;
            });

            // 添加专业信息
            if (ApplyTypeUtil.isMajorSchoolType(applyType)) {
                // 专业+院校模式：专业信息在外部字段
                VolunteerMajor major = createVolunteerMajorFromSchoolDetail(schoolDetail);
                schoolGroup.getMajorList().add(major);
                log.debug("OTOO模式：添加专业 {} 到院校 {} (planSchoolDataId: {})",
                        major.getMajorName(), schoolGroup.getSchoolName(), planSchoolDataId);
            } else {
                // 院校专业组模式：专业信息在majorVOList中
                if (schoolDetail.getMajorVOList() != null) {
                    for (ProgramPageDTO.MajorVO majorVO : schoolDetail.getMajorVOList()) {
                        VolunteerMajor major = createVolunteerMajorFromMajorVO(schoolDetail, majorVO);
                        if (major != null) {
                            schoolGroup.getMajorList().add(major);
                        }
                    }
                }
            }
        }

        // 过滤掉没有专业的院校组，避免后续处理中出现空指针异常
        List<VolunteerSchoolGroup> result = new ArrayList<>();
        for (VolunteerSchoolGroup group : schoolGroupMap.values()) {
            if (group.getMajorList() != null && !group.getMajorList().isEmpty()) {
                result.add(group);
            } else {
                log.warn("跳过没有专业的院校: {} (ID: {})", group.getSchoolName(), group.getSchoolId());
            }
        }

        log.info("数据转换完成，原始院校数量: {}, 有效院校数量: {}", schoolGroupMap.size(), result.size());
        return result;
    }

    /**
     * 从SchoolDetail创建VolunteerMajor（专业+院校模式）
     */
    private VolunteerMajor createVolunteerMajorFromSchoolDetail(ProgramPageDTO.SchoolDetail schoolDetail) {
        VolunteerMajor major = new VolunteerMajor();


        major.setMajorId(schoolDetail.getMajorId());

        // 专业信息（外部字段）
        major.setMajorName(schoolDetail.getMajorUnitName());
        major.setMajorUnitCode(schoolDetail.getMajorUnitCode());
        major.setPlanMajorDataId(schoolDetail.getPlanMajorDataId());
        major.setCategoryId(schoolDetail.getCategoryId());
        major.setSubCategoryId(schoolDetail.getSubCategoryId());

        // 专业录取信息（使用院校的录取信息）
        major.setMajorEnrollRatio(parseEnrollRatio(schoolDetail.getEnrollRatio()));
        major.setMajorEnrollRatioStr(schoolDetail.getEnrollRatio());
        major.setMajorVolunteerLevel(schoolDetail.getVolunteerLevel() != null ? schoolDetail.getVolunteerLevel().getCode() : null);

        // 其他信息
        major.setPlanNum(schoolDetail.getPlanNum());
        major.setScore(parseScore(schoolDetail.getSchoolScore()));
        major.setPos(schoolDetail.getSchoolPos());
        major.setSelectInfo(schoolDetail.getSelectInfo());
        major.setIsNew(schoolDetail.getMajorIsNew());
        major.setIsDoubleFirstMajor(schoolDetail.getIsDoubleFirstMajor());
        //学费
        major.setPlanMoney(schoolDetail.getPlanMoney());
        //学制
        major.setDuration(schoolDetail.getPlanDuration());

        //设置专业历史录取数据（转换为简化结构）
        major.setHistoryRecords(convertSubVOListToHistoryRecords(schoolDetail.getSubVOList()));

        return major;
    }

    /**
     * 从MajorVO创建VolunteerMajor（院校专业组模式）
     */
    private VolunteerMajor createVolunteerMajorFromMajorVO(ProgramPageDTO.SchoolDetail schoolDetail, ProgramPageDTO.MajorVO majorVO) {
        VolunteerMajor major = new VolunteerMajor();

        // 生成唯一ID
        major.setMajorId(majorVO.getMajorId());

        // 专业信息（MajorVO字段）
        major.setMajorName(majorVO.getMajorName());
        major.setMajorUnitCode(majorVO.getUnitCode());
        major.setPlanMajorDataId(majorVO.getPlanMajorDataId());
        major.setCategoryId(majorVO.getCategoryId());
        major.setSubCategoryId(majorVO.getSubCategoryId());

        // 专业录取信息（使用专业的录取信息）
        major.setMajorEnrollRatio(parseEnrollRatio(majorVO.getEnrollRatio()));
        major.setMajorEnrollRatioStr(majorVO.getEnrollRatio());
        major.setMajorVolunteerLevel(majorVO.getVolunteerLevel() != null ? majorVO.getVolunteerLevel().getCode() : null);

        // 其他信息
        major.setPlanNum(majorVO.getPlanNum());
        major.setScore(majorVO.getScore());
        major.setPos(majorVO.getPos());
        major.setSelectInfo(majorVO.getSelectInfo());
        major.setIsNew(majorVO.getIsNew());
        major.setIsDoubleFirstMajor(majorVO.getIsDoubleFirstMajor());

        major.setPlanMoney(majorVO.getMoney());
        major.setDuration(majorVO.getDuration());
        //设置专业录取历史数据（转换为简化结构）
        major.setHistoryRecords(convertSubVOListToHistoryRecords(majorVO.getSubVOList()));

        return major;
    }

    /**
     * 解析录取率字符串为数值
     */
    private Double parseEnrollRatio(String enrollRatioStr) {
        if (enrollRatioStr == null || enrollRatioStr.isEmpty()) {
            return null;
        }
        try {
            // 移除百分号并转换为数值
            return Double.parseDouble(enrollRatioStr.replace("%", ""));
        } catch (NumberFormatException e) {
            log.warn("解析录取率失败: {}", enrollRatioStr);
            return null;
        }
    }

    /**
     * 解析分数字符串为数值
     */
    private Integer parseScore(String scoreStr) {
        if (scoreStr == null || scoreStr.isEmpty()) {
            return null;
        }
        try {
            Double d = Double.parseDouble(scoreStr);
            return d.intValue();
        } catch (NumberFormatException e) {
            log.warn("解析分数失败: {}", scoreStr);
            return null;
        }
    }

    /**
     * 将 SubVO 列表转换为简化的 HistoryRecordDTO 列表
     */
    private List<HistoryRecordDTO> convertSubVOListToHistoryRecords(List<ProgramPageDTO.SubVO> subVOList) {
        if (subVOList == null || subVOList.isEmpty()) {
            return new ArrayList<>();
        }
        
        return subVOList.stream()
                .map(HistoryRecordDTO::fromSubVO)
                .filter(record -> record != null && record.getYear() != null)
                .collect(java.util.stream.Collectors.toList());
    }
}
