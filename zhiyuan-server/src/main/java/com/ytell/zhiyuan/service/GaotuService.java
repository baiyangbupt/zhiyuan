package com.ytell.zhiyuan.service;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.date.DateUtil;
import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
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
import java.net.SocketTimeoutException;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

@Slf4j
@Service
public class GaotuService {

    private static final int VOLUNTEER_DATA_TIMEOUT_STATUS = 110;
    private static final String VOLUNTEER_DATA_TIMEOUT_MESSAGE = "志愿数据获取超时";

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
                if (isVolunteerDataTimeoutException(e)) {
                    throw e;
                }
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
        ResponseDTO<ProgramPageDTO> response;
        try {
            response = gaotuClient.getProgramList(req);
        } catch (RuntimeException e) {
            throwVolunteerDataTimeoutIfNeeded(e);
            throw e;
        }
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

        if (!Boolean.FALSE.equals(gaotuProperties.getProgramDataPagedEnabled())) {
            try {
                return queryAllProgramDataPaged(req);
            } catch (RuntimeException e) {
                throwVolunteerDataTimeoutIfNeeded(e);
                if (!Boolean.FALSE.equals(gaotuProperties.getProgramDataFallbackEnabled())) {
                    log.warn("queryAllProgramData paged failed, fallback to full endpoint reason={}", e.getMessage());
                } else {
                    throw e;
                }
            }
        }
        return queryAllProgramDataLegacy(req);

    }

    private JSONObject queryAllProgramDataLegacy(ProgramPageReq req) {
        log.info("查询志愿方案-全量接口-方案数据, 请求参数: {}", req);
        ResponseDTO<JSONObject> response;
        try {
            response = gaotuClient.getProgramFullList(req);
        } catch (RuntimeException e) {
            throwVolunteerDataTimeoutIfNeeded(e);
            throw e;
        }
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

    private JSONObject queryAllProgramDataPaged(ProgramPageReq req) {
        int reinitTimes = Math.max(0, defaultInteger(gaotuProperties.getProgramDataSessionReinitTimes(), 1));
        RuntimeException lastError = null;
        for (int attempt = 0; attempt <= reinitTimes; attempt++) {
            try {
                return queryAllProgramDataPagedOnce(req, attempt);
            } catch (RuntimeException e) {
                throwVolunteerDataTimeoutIfNeeded(e);
                lastError = e;
                log.warn("queryAllProgramDataPaged attempt failed attempt={} reinitTimes={} reason={}",
                        attempt, reinitTimes, e.getMessage());
            }
        }
        throw lastError == null ? new BusinessException(110, "查询志愿方案分页数据失败") : lastError;
    }

    private JSONObject queryAllProgramDataPagedOnce(ProgramPageReq req, int initAttempt) {
        long initStart = System.currentTimeMillis();
        ResponseDTO<JSONObject> initResponse;
        try {
            initResponse = gaotuClient.getProgramFullListInit(req);
        } catch (RuntimeException e) {
            throwVolunteerDataTimeoutIfNeeded(e);
            throw e;
        }
        JSONObject initData = requireSuccessfulProgramDataResponse(initResponse, "分页初始化");
        String sessionId = initData.getString("sessionId");
        long total = getRequiredLong(initData, "total", "分页初始化");
        long pages = getRequiredLong(initData, "pages", "分页初始化");
        long pageSize = getRequiredLong(initData, "pageSize", "分页初始化");
        if (Strings.isNullOrEmpty(sessionId) || total < 0 || pages < 0 || (pages > 0 && pageSize <= 0)
                || initData.get("model") == null) {
            throw new BusinessException(110, "查询志愿方案分页初始化数据不完整");
        }
        log.info("queryAllProgramDataPagedInit areaId={} batch={} year={} prepareType={} total={} pages={} pageSize={} sessionIdPrefix={} costMs={} initAttempt={}",
                req.getAreaId(),
                req.getBatch(),
                req.getYear(),
                req.getPrepareType(),
                total,
                pages,
                pageSize,
                sessionId.length() <= 8 ? sessionId : sessionId.substring(0, 8),
                System.currentTimeMillis() - initStart,
                initAttempt);

        JSONArray mergedDetails = new JSONArray();
        for (long current = 1; current <= pages; current++) {
            JSONObject pageData = queryAllProgramDataPageWithRetry(sessionId, current, pageSize, pages);
            JSONArray detailList = pageData.getJSONArray("detailList");
            if (detailList == null) {
                throw new BusinessException(110, "查询志愿方案分页明细为空");
            }
            mergedDetails.addAll(detailList);
        }

        if (mergedDetails.size() != total) {
            throw new BusinessException(110, "查询志愿方案分页数据不完整");
        }
        int distinctPlanMajorCount = countDistinctPlanMajorDataIds(mergedDetails);
        int missingPlanMajorCount = countMissingPlanMajorDataIds(mergedDetails);
        log.info("queryAllProgramDataPagedMerge total={} mergedCount={} distinctPlanMajorDataIdCount={} missingPlanMajorDataIdCount={}",
                total, mergedDetails.size(), distinctPlanMajorCount, missingPlanMajorCount);

        JSONObject merged = new JSONObject();
        merged.put("model", initData.get("model"));
        merged.put("type", initData.get("type"));
        merged.put("policy", initData.get("policy"));
        merged.put("isLatestPolicy", initData.get("isLatestPolicy"));
        merged.put("detailList", mergedDetails);
        return merged;
    }

    private JSONObject queryAllProgramDataPageWithRetry(String sessionId, long current, long pageSize, long pages) {
        int retryTimes = Math.max(0, defaultInteger(gaotuProperties.getProgramDataPageRetryTimes(), 2));
        RuntimeException lastError = null;
        for (int retry = 0; retry <= retryTimes; retry++) {
            long pageStart = System.currentTimeMillis();
            try {
                ExpertAIProgramPageReq pageReq = new ExpertAIProgramPageReq();
                pageReq.setSessionId(sessionId);
                pageReq.setCurrent(current);
                pageReq.setSize(pageSize);
                ResponseDTO<JSONObject> pageResponse = gaotuClient.getProgramFullListPage(pageReq);
                JSONObject pageData = requireSuccessfulProgramDataResponse(pageResponse, "分页明细");
                JSONArray detailList = pageData.getJSONArray("detailList");
                if (detailList == null) {
                    throw new BusinessException(110, "查询志愿方案分页明细为空");
                }
                Long responseCurrent = pageData.getLong("current");
                if (responseCurrent != null && responseCurrent.longValue() != current) {
                    log.warn("queryAllProgramDataPagedPage current mismatch requestCurrent={} responseCurrent={}",
                            current, responseCurrent);
                }
                log.info("queryAllProgramDataPagedPage current={} pages={} detailCount={} retry={} costMs={}",
                        current, pages, detailList.size(), retry, System.currentTimeMillis() - pageStart);
                return pageData;
            } catch (RuntimeException e) {
                throwVolunteerDataTimeoutIfNeeded(e);
                lastError = e;
                log.warn("queryAllProgramDataPagedPage failed current={} pages={} retry={} reason={}",
                        current, pages, retry, e.getMessage());
            }
        }
        throw lastError == null ? new BusinessException(110, "查询志愿方案分页明细失败") : lastError;
    }

    private JSONObject requireSuccessfulProgramDataResponse(ResponseDTO<JSONObject> response, String step) {
        if (response == null) {
            throw new BusinessException(110, "查询志愿方案" + step + "响应为空");
        }
        if (response.getCode() == null || response.getCode() != 0) {
            String msg;
            if (response.getCode() != null && response.getCode() == -9) {
                msg = "对不起，您所选的批次内没有查到可报的志愿，请调整您的分数或批次";
            } else {
                msg = response.getMsg();
            }
            throw new BusinessException(response.getCode() == null ? 110 : response.getCode(), msg);
        }
        if (response.getData() == null) {
            throw new BusinessException(404, "查询志愿方案" + step + "数据为空");
        }
        return response.getData();
    }

    private long getRequiredLong(JSONObject data, String key, String step) {
        Object value = data == null ? null : data.get(key);
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        if (value instanceof String && !Strings.isNullOrEmpty(((String) value).trim())) {
            try {
                return Long.parseLong(((String) value).trim());
            } catch (NumberFormatException ignored) {
                throw new BusinessException(110, "查询志愿方案" + step + "字段格式错误: " + key);
            }
        }
        throw new BusinessException(110, "查询志愿方案" + step + "缺少字段: " + key);
    }

    private int countDistinctPlanMajorDataIds(JSONArray details) {
        Set<String> ids = new LinkedHashSet<String>();
        for (Object item : details == null ? new JSONArray() : details) {
            if (item instanceof JSONObject) {
                String id = ((JSONObject) item).getString("planMajorDataId");
                if (!Strings.isNullOrEmpty(id)) {
                    ids.add(id);
                }
            }
        }
        return ids.size();
    }

    private int countMissingPlanMajorDataIds(JSONArray details) {
        int missing = 0;
        for (Object item : details == null ? new JSONArray() : details) {
            if (!(item instanceof JSONObject) || Strings.isNullOrEmpty(((JSONObject) item).getString("planMajorDataId"))) {
                missing++;
            }
        }
        return missing;
    }

    private int defaultInteger(Integer value, int defaultValue) {
        return value == null ? defaultValue : value;
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
        ResponseDTO<RecommendNumResponse> response;
        try {
            response = gaotuClient.getRecommendProgramNum(req);
        } catch (RuntimeException e) {
            throwVolunteerDataTimeoutIfNeeded(e);
            throw e;
        }
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
     *
     * <p><b>年份回退口径（2026-10-07 独立审查 M2）</b>：上游按请求年份查不到（code≠0 或
     * {@code data:null}，后者是"该省/该年份没有一分一段"的正常形状）时，**只有调用方根本没指定
     * 年份**才允许退回"当年"再试一次。以前是无条件把请求里的年份改成当年再查——指定了
     * 2025 却被静默换成 2026 的数据，还会被补录链路当成 2025 的位次落库（跨年串数据）。
     * 指定了年份就**不换**：查不到如实回 {@code null}，调用方保持位次为空（不造数）。</p>
     */
    public ScorePositionRangeRes getScorePositionRange(ScorePositionRangeReq req) {
        log.info("开始查询分数位次范围, 请求参数: {}", JSON.toJSONString(req));
        ResponseDTO<ScorePositionRangeRes> response = gaotuClient.getScorePositionRange(req);
        log.debug("查询分数位次范围完成, 响应结果: {}", JSON.toJSONString(response));

        if (isScorePositionFailure(response)) {
            log.error("查询分数位次范围失败:code:{},msg:{}",
                    response == null ? null : response.getCode(),
                    response == null ? null : response.getMsg());
            if (Strings.isNullOrEmpty(req.getYear())) {
                String fallbackYear = DateUtil.year(new Date()) + "";
                log.warn("getScorePositionRange retry with current year {} reason=year_not_specified req={}",
                        fallbackYear, JSON.toJSONString(req));
                req.setYear(fallbackYear);
                response = gaotuClient.getScorePositionRange(req);
            } else {
                log.warn("getScorePositionRange no retry reason=year_pinned year={}（不把别的年份的数据当请求年份）",
                        req.getYear());
            }
        }

        if (response == null || response.getData() == null) {
            return null;
        }

        return response.getData();
    }

    /** 位次查询失败判定：空响应/非 0 码/无数据都算失败（code=0 且 data:null 是"没有这份数据"）。 */
    private boolean isScorePositionFailure(ResponseDTO<ScorePositionRangeRes> response) {
        return response == null || response.getCode() == null || response.getCode() != 0
                || response.getData() == null;
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

    private static void throwVolunteerDataTimeoutIfNeeded(RuntimeException e) {
        if (isVolunteerDataTimeoutException(e)) {
            throw new BusinessException(VOLUNTEER_DATA_TIMEOUT_STATUS, VOLUNTEER_DATA_TIMEOUT_MESSAGE);
        }
    }

    private static boolean isVolunteerDataTimeoutException(Throwable throwable) {
        Throwable current = throwable;
        while (current != null) {
            if (current instanceof SocketTimeoutException) {
                return true;
            }
            String message = current.getMessage();
            if (VOLUNTEER_DATA_TIMEOUT_MESSAGE.equals(message)) {
                return true;
            }
            if (message != null) {
                String lowerMessage = message.toLowerCase(Locale.ROOT);
                if (lowerMessage.contains("timeout") || lowerMessage.contains("timed out")) {
                    return true;
                }
            }
            current = current.getCause();
        }
        return false;
    }
}
