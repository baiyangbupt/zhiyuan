package com.ytell.zhiyuan.service;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.date.DateUtil;
import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.config.GaotuProperties;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.gaotu.*;
import com.ytell.zhiyuan.model.dto.gaotu.req.*;
import com.ytell.zhiyuan.model.dto.gaotu.res.*;
import com.ytell.zhiyuan.model.dto.inner.SaveProgramDetailDto;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.util.Assert;

import java.math.BigDecimal;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

@Slf4j
@Service
public class GaotuService {

    @Autowired
    GaotuProperties gaotuProperties;
    @Autowired
    private GaotuClient gaotuClient;

    public static void main(String[] args) {
        String name = "专家方案-" + DateUtil.format(new Date(), "MMddHHmm");
        System.out.println(name);
    }


    public List<String> getExamYearList() {
        try {
            ResponseDTO<CommonInfoResponse> response = gaotuClient.getCommonInfo();
            if (response != null && response.getCode() != null && response.getCode() == 0
                    && response.getData() != null
                    && CollectionUtil.isNotEmpty(response.getData().getExamYearList())) {
                return response.getData().getExamYearList();
            }
            log.warn("getExamYearList返回为空或失败: {}", JSON.toJSONString(response));
        } catch (Exception e) {
            log.warn("getExamYearList调用失败", e);
        }
        return Collections.emptyList();
    }

    /**
     * 查询并保存志愿信息
     *
     * @param req 批次数据查询请求
     * @return 处理结果
     */
    public SaveProgramDetailDto queryAndSaveProgram(ProgramPageReq req, RecommendNumResponse recommendNum) {
        // 参数校验
        Assert.notNull(req, "请求参数不能为空");
        Assert.notNull(req.getAreaId(), "省份ID不能为空");
        Assert.hasText(req.getPrepareType(), "填报类型不能为空");
        ProgramPageDTO programData = null;
        boolean querySuccess = false;
        boolean needValidate = true;

        // 尝试查询志愿方案，处理异常并调整参数
        for (int attempt = 0; attempt < 4 && !querySuccess; attempt++) {
            try {
                programData = queryProgramData(req);
                if (needValidate) {
                    validateProgramData(programData, recommendNum);
                }
                querySuccess = true;
            } catch (BusinessException e) {
                querySuccess = false;
                log.error("queryAndSaveProgram:查询方案报错:attempt:{},code:{},msg:{}", attempt, e.getStatus(), e.getMessage());
                if (attempt == 0) {
                    // 第一次失败：移除专业过滤
                    req.setMajorIdList(Lists.newArrayList());
                    req.setNatureList(Lists.newArrayList());
                } else if (attempt == 1) {
                    // 第二次失败：移除专业&城市过滤
                    req.setCities(Lists.newArrayList());
                } else if (attempt == 2) {
                    // 第三次
                    //不再校验，直接查询一次
                    needValidate = false;
                }
            }
        }

        if (!querySuccess || programData == null) {
            throw new BusinessException(404, "查询志愿方案失败");
        }
        // 保存生成方案
        Long programId = this.saveProgramData(req, programData);
        // 返回成功响应
        SaveProgramDetailDto saveProgramDetailDto = new SaveProgramDetailDto();
        saveProgramDetailDto.setProgramId(programId);
        saveProgramDetailDto.setVolunteerPolicyId(programData.getModel().getVolunteerPolicyId());
        saveProgramDetailDto.setProgramPageDTO(programData);
        return saveProgramDetailDto;
    }

    private void validateProgramData(ProgramPageDTO programData, RecommendNumResponse recommendNum) {
        if (programData == null || programData.getDetailList() == null || programData.getDetailList().isEmpty()) {
            throw new BusinessException(404, "未查询到志愿方案数据");
        }
        if (recommendNum.getSchoolNum() != null && recommendNum.getSchoolNum() > programData.getModel().getSchoolTotalNum()) {
            throw new BusinessException(404, "查询志愿学校数量不足");
        }
        if (recommendNum.getMajorNum() != null && recommendNum.getMajorNum() > programData.getModel().getMajorTotalNum()) {
            throw new BusinessException(404, "查询志愿专业数量不足");
        }
    }

    private VolunteerProgramSaveDTO toSaveProgramDto(ProgramPageReq req, ProgramPageDTO programData) {

        VolunteerProgramSaveDTO saveDTO = new VolunteerProgramSaveDTO();
        // 设置基本信息
        //如果id有值，则代表更新
        if (req.getId() != null) {
            saveDTO.setId(req.getId());
        }
        saveDTO.setMemberId(req.getMemberId());
        saveDTO.setAreaId(req.getAreaId());
        saveDTO.setYear(req.getYear());
        saveDTO.setVolunteerPolicyId(Long.valueOf(programData.getModel().getVolunteerPolicyId()));
        // 默认为0，表示新建方案
        saveDTO.setParentId(0L);
        // 自动生成方案
        saveDTO.setManner("EXPERT_AI");
        // 系统生成，设置为0
        saveDTO.setExpertUserId(0L);
        String name = "专家方案-" + DateUtil.format(new Date(), "MMddHHmm");
        saveDTO.setName(name);
        saveDTO.setBatch(programData.getModel().getBatch());
        saveDTO.setSubjectType(programData.getModel().getSubjectType().getCode());
        saveDTO.setScore(new BigDecimal(programData.getModel().getScore()));
        saveDTO.setPos(programData.getModel().getPos());
        saveDTO.setType(programData.getModel().getType().getCode());


        // 设置学校信息
        AtomicInteger schoolIndexCounter = new AtomicInteger(0);
        List<VolunteerProgramSchoolSaveDTO> schoolList = programData.getDetailList().stream()
                .map(detail -> {
                    VolunteerProgramSchoolSaveDTO school = new VolunteerProgramSchoolSaveDTO();
                    school.setPlanSchoolDataId(detail.getPlanSchoolDataId());
                    school.setVolunteerLevel(detail.getVolunteerLevel().getCode());
                    school.setSortValue(schoolIndexCounter.getAndIncrement());
                    return school;
                })
                .collect(Collectors.toList());
        saveDTO.setSchoolSaveDTOList(schoolList);

        // 设置专业信息
        //当type为OTOO/ OTOOWL时，不需要传majorSaveDTOList
        String typeCode = programData.getType().getCode();
        if (!"OTOO".equals(typeCode) && !"OTOOWL".equals(typeCode)) {
            AtomicInteger majorIndexCounter = new AtomicInteger(0);
            List<VolunteerProgramMajorSaveDTO> majorList = programData.getDetailList().stream()
                    .flatMap(detail -> detail.getMajorVOList().stream()
                            .map(major -> {
                                VolunteerProgramMajorSaveDTO majorSave = new VolunteerProgramMajorSaveDTO();
                                majorSave.setPlanMajorDataId(Long.valueOf(major.getPlanMajorDataId()));
                                majorSave.setVolunteerLevel(major.getVolunteerLevel().getCode());
                                majorSave.setSortValue(majorIndexCounter.getAndIncrement()); // 设置索引值
                                return majorSave;
                            }))
                    .collect(Collectors.toList());
            saveDTO.setMajorSaveDTOList(majorList);
        }

        // 设置选科信息
        List<VolunteerProgramSubjectSaveDTO> subjectList = programData.getModel().getSubjectList().stream()
                .map(subject -> {
                    VolunteerProgramSubjectSaveDTO subjectSave = new VolunteerProgramSubjectSaveDTO();
                    subjectSave.setSubject(subject.getSubject());
                    subjectSave.setIsFirst(subject.getIsFirst());
                    return subjectSave;
                })
                .collect(Collectors.toList());
        saveDTO.setSubjectSaveDTOList(subjectList);
        return saveDTO;
    }

    /**
     * 查询方案
     *
     * @param req
     * @return
     */
    public ProgramPageDTO queryProgramData(ProgramPageReq req) {

        // 参数校验
        Assert.notNull(req, "请求参数不能为空");
        Assert.notNull(req.getAreaId(), "省份ID不能为空");
        Assert.hasText(req.getPrepareType(), "填报类型不能为空");

        //新疆特殊处理
        if ("650000".equals(req.getAreaId())) {
            req.setSubjects(null);
        }

        log.info("开始查询志愿方案数据, 请求参数: {}", req);
        ResponseDTO<ProgramPageDTO> response = gaotuClient.getProgramList(req);
        log.debug("查询志愿方案数据完成, 响应结果: {}", JSON.toJSONString(response));

        if (response.getCode() != 0) {
            log.error("查询志愿方案数据失败:code:{},msg:{}", response.getCode(), response.getMsg());
            throw new BusinessException(response.getCode(), response.getMsg());
        }
        if (response.getData() == null) {
            throw new BusinessException(404, "查询志愿方案数据为空");
        }
        return response.getData();

    }

    /**
     * 查询方案-最新全量
     *
     * @param req
     * @return
     */
    public JSONObject queryAllProgramData(ProgramPageReq req) {

        // 参数校验
        Assert.notNull(req, "请求参数不能为空");
        Assert.notNull(req.getAreaId(), "省份ID不能为空");
        Assert.hasText(req.getPrepareType(), "填报类型不能为空");

        //新疆特殊处理
        if ("650000".equals(req.getAreaId())) {
            req.setSubjects(null);
        }

        log.info("查询志愿方案-全量接口-方案数据, 请求参数: {}", req);
        ResponseDTO<JSONObject> response = gaotuClient.getProgramFullList(req);
        log.debug("查询志愿方案-全量接口-数据完成, 响应结果: {}", JSON.toJSONString(response));

        if (response.getCode() != 0) {
            log.error("查询志愿方案-全量接口-数据失败:code:{},msg:{}", response.getCode(), response.getMsg());
            String msg;
            if (response.getCode() == -9) {
                msg = "对不起，您所选的批次内没有查到可报的志愿，请调整您的分数或批次";
            } else {
                msg = response.getMsg();
            }
            throw new BusinessException(response.getCode(), msg);
        }
        if (response.getData() == null) {
            throw new BusinessException(404, "查询志愿方案数据为空");
        }
        return response.getData();

    }

    /**
     * 保存志愿
     *
     * @param req
     * @return
     */
    public Long saveProgramData(ProgramPageReq req, ProgramPageDTO programData) {

        VolunteerProgramSaveDTO saveDTO = toSaveProgramDto(req, programData);
        log.info("开始保存志愿数据, 方案保存数据: {}", JSON.toJSONString(saveDTO));
        // 调用保存接口
        ResponseDTO<Long> response = gaotuClient.saveProgramInfo(saveDTO);
        log.info("保存志愿数据完成, 响应结果: {}", JSON.toJSONString(response));
        if (response.getCode() != 0) {
            log.error("保存志愿数据失败:code:{},msg:{}", response.getCode(), response.getMsg());
            //对方高并发会有主键冲突的问题，需要重试来解决。很扯淡，但是也只能这样搞。
            if (response.getCode().equals(84007)) {
                response = gaotuClient.saveProgramInfo(saveDTO);
                if (response.getCode() != 0) {
                    log.error("保存志愿数据重试仍失败:code:{},msg:{}", response.getCode(), response.getMsg());
                    throw new BusinessException(response.getCode(), "保存志愿数据失败");
                }
            } else {
                throw new BusinessException(response.getCode(), "保存志愿数据失败");
            }
        }
        return response.getData();
    }

    /**
     * 获取区域志愿数量
     *
     * @param req
     * @return
     */

    public RecommendNumResponse getRecommendProgramNum(RecommendNumReq req) {
        log.info("查询院校专业数量数据:req:{}", JSONObject.toJSONString(req));
        ResponseDTO<RecommendNumResponse> response = gaotuClient.getRecommendProgramNum(req);
        if (response.getCode() != 0 || response.getData() == null) {
            log.error("查询院校专业数量数据失败:code:{},msg:{}", response.getCode(), response.getMsg());
            throw new BusinessException(110, response.getMsg());
        }
        return response.getData();
    }

    /**
     * 获取最新的测评报告
     *
     * @param userId
     * @param reportType
     * @return
     */
    public JSONArray getLastReport(Long userId, Integer reportType) {
        ListReportInfoRpcReq req = new ListReportInfoRpcReq();
        req.setReportType(reportType);
        req.setUserId(userId);
        ResponseDTO<ListReportInfoDTO> responseDTO = gaotuClient.getReportList(req);
        if (responseDTO.getCode() != 0 ||
                responseDTO.getData() == null ||
                CollectionUtil.isEmpty(responseDTO.getData().getReportInfoList())) {
            log.error("查询评测报告数据列表失败:code:{},msg:{}", responseDTO.getCode(), responseDTO.getMsg());

            throw new BusinessException(110, "未查到测试报告");
        }
        Long reportId = responseDTO.getData().getReportInfoList().get(0).getReportId();
        GetReportInfoReq reportInfoReq = new GetReportInfoReq();
        reportInfoReq.setUserId(userId);
        reportInfoReq.setReportId(reportId);
        ResponseDTO<GetReportInfoDTO> reportInfoDTO = gaotuClient.getReportInfo(reportInfoReq);

        if (reportInfoDTO.getCode() != 0 || reportInfoDTO.getData() == null || CollectionUtil.isEmpty(reportInfoDTO.getData().getResults())) {
            log.error("查询评测报告数据详情失败:code:{},msg:{}", responseDTO.getCode(), responseDTO.getMsg());

            throw new BusinessException(110, "未查到测试报告");
        }
        return reportInfoDTO.getData().getResults();
    }

    public Boolean deleteUserScoreForm(Long formId, Long memberId) {
        log.info("deleteUserScoreForm:formId:{},memberId:{}", formId, memberId);
        ResponseDTO<Boolean> responseDTO = gaotuClient.deleteUserScoreForm(formId, memberId);
        if (responseDTO.getCode() != 0) {
            log.error("deleteUserScoreForm:error:code:{},msg:{}", responseDTO.getCode(), responseDTO.getMsg());
        }
        return Boolean.TRUE;
    }

    public Boolean needAuth() {
        return gaotuProperties.getAuthOpen();
    }

    public AuthResponseDto auth(Long memberId) {
        if (!gaotuProperties.getAuthOpen()) {
            AuthResponseDto res = new AuthResponseDto();
            res.setCanUserChat(true);
            return res;
        }
        try {
            log.info("auth:memberId:{}", memberId);
            ResponseDTO<AuthResponseDto> responseDTO = gaotuClient.auth(memberId);
            log.info("auth:memberId:{},res:{}", memberId, JSON.toJSONString(responseDTO));
            if (responseDTO.getCode() == 0 && responseDTO.getData() != null) {
                return responseDTO.getData();
            }
        } catch (Exception e) {
            log.error("auth:error", e);
        }
        AuthResponseDto res = new AuthResponseDto();
        res.setCanUserChat(true);
        return res;
    }

    /**
     * 查询院校专业方案
     * 输入: 省份、选科、批次、分数、冲稳保数量N
     * 输出: 按照指定的数量N提供用户可以报考的院校专业以及相应的录取率
     *
     * @param req
     * @return
     */
    public List<QueryProgramByLimitNumRes> queryProgramByLimitNum(QueryProgramLimitNumReq req) {
        ResponseDTO<List<QueryProgramByLimitNumRes>> response = gaotuClient.queryProgramByLimitNum(req);
        if (response.getCode() != 0 || response.getData() == null) {
            log.error("查询院校专业方案失败:code:{},msg:{}", response.getCode(), response.getMsg());
            throw new BusinessException(110, response.getMsg());
        }
        return response.getData();
    }

    /**
     * 查询院校专业录取分数
     * 输入: 年份、省份、批次、选科、院校、专业
     * 输出: 对应分数线(如果包含院校专业给出对应每个专业的分数线)
     */
    public List<QuerySchoolMajorScoreLineRes> querySchoolMajorScoreLine(QuerySchoolMajorScoreLineReq req) {
        ResponseDTO<List<QuerySchoolMajorScoreLineRes>> response = gaotuClient.querySchoolMajorScoreLine(req);
        if (response.getCode() != 0 || response.getData() == null) {
            log.error("查询院校专业录取分数失败:code:{},msg:{}", response.getCode(), response.getMsg());
            throw new BusinessException(110, response.getMsg());
        }
        return response.getData();
    }

    /**
     * 根据分数获取位次范围
     * 输入: 地区ID、科目类型、数据级别、年份、分数
     * 输出: 对应的位次范围信息
     */
    public ScorePositionRangeRes getScorePositionRange(ScorePositionRangeReq req) {
        log.info("开始查询分数位次范围, 请求参数: {}", JSON.toJSONString(req));
        ResponseDTO<ScorePositionRangeRes> response = gaotuClient.getScorePositionRange(req);
        log.debug("查询分数位次范围完成, 响应结果: {}", JSON.toJSONString(response));

        if (response.getCode() != 0 || response.getData() == null) {
            log.error("查询分数位次范围失败:code:{},msg:{}", response.getCode(), response.getMsg());
            req.setYear(DateUtil.year(new Date()) + "");
            response = gaotuClient.getScorePositionRange(req);
        }

        if (response.getData() == null) {
            return null;
        }

        return response.getData();
    }

    public UserInfoByTokenRes getUserInfoByToken(String token) {
        log.info("开始根据token查询用户信息, 请求参数: {}", token);
        ResponseDTO<UserInfoByTokenRes> response = gaotuClient.getUserInfoByToken(token);
        if (response == null || response.getCode() != 0 || response.getData() == null) {
            String responseMsg = response == null ? null : response.getMsg();
            log.error("开始根据token查询用户信息失败:code:{},msg:{}",
                    response == null ? null : response.getCode(), responseMsg);
            if ("用户选科信息不存在".equals(responseMsg)) {
                throw new BusinessException(110, "请在首页完善高考省份和选科信息后再进入AI智能填报");
            }
            throw new BusinessException(110, "链接已经失效，请尝试重新点击进入");
        }
        log.info("getUserInfoByToken:返回:{}",JSON.toJSONString(response));
        return response.getData();
    }

    public UserRightsByUserIdRes getUserRights(String userId) {
        log.info("开始根据userId查询用户权益信息, 请求参数: {}", userId);
        ResponseDTO<UserRightsByUserIdRes> response = gaotuClient.getUserRights(userId);
        if (response.getCode() != 0 || response.getData() == null) {
            log.error("开始根据userId查询用户权益信息失败:code:{},msg:{}", response.getCode(), response.getMsg());
            throw new BusinessException(110, "您尚未购买该服务，暂时无法使用");
        }
        log.info("getUserRights:返回:{}",JSON.toJSONString(response));
        return response.getData();
    }
}

