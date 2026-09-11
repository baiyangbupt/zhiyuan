package com.ytell.zhiyuan.manager.gaotu;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.alibaba.fastjson.TypeReference;
import com.google.common.base.Strings;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.config.GaotuProperties;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.JsonHttpUtil;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceSignRequest;
import com.ytell.zhiyuan.model.dto.gaotu.*;
import com.ytell.zhiyuan.model.dto.gaotu.req.*;
import com.ytell.zhiyuan.model.dto.gaotu.res.*;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.service.biz.EvidenceLedgerService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
@EnableConfigurationProperties(GaotuProperties.class)
public class GaotuClient {

    private static final String USER_MEMBER_PATH = "/user/session/getUid";
    private static final String MEMBER_SCORE_PATH = "/hl-wish/ci/ci_feign/member/noToken/getMemberScoreByMemberId";
    private static final String COMMON_INFO_PATH = "/hl-wish/ci/memberWhitelist/noToken/commonInfo";
    private static final String BATCH_LIST_PATH = "/hl-wish/ci/h5/batchData/anno/batchListByPolicy";
    private static final String REPORT_LIST_PATH = "/hl-wish/practice-evaluation/feign/evaluation/report/list";
    private static final String REPORT_INFO_PATH = "/hl-wish/practice-evaluation/feign/evaluation/report/getById";
    private static final String PROGRAM_LIST_PATH = "/hl-wish/ci/ci_feign/volunteer/generateExpertAIProgram";
    private static final String PROGRAM_LIST_ALL_PATH = "/hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgram";
    private static final String PROGRAM_LIST_ALL_INIT_PATH = "/hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgramInit";
    private static final String PROGRAM_LIST_ALL_PAGE_PATH = "/hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgramPage";

    private static final String PROGRAM_SAVE_PATH = "/hl-wish/ci/ci_feign/volunteer/saveOrUpdateVolunteerProgram";
    private static final String MACHINE_AUDIT_PATH = "/rk/api/ugc/machine/audit/v1";
    private static final String RECOMMEND_PROGRAM_NUM_PATH = "/hl-wish/ci/ci_feign/volunteer/getRecommendProgramNum";
    private static final String DELETE_SCORE_FORM_PATH = "/hl-wish/ci/ci_feign/member/noToken/deleteMemberForm";

    private static final String AUTH_PATH = "/hl-wish/ci/ci_feign/member/noToken/ai/canUserChat";

    private static final String QUERY_PROGRAM_BY_LIMIT_NUM = "/hl-wish/ci/ci_feign/volunteer/queryProgramByLimitNum";

    private static final String QUERY_SCHOOL_MAJOR_SCORE_LINE = "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine";
    
    private static final String SCORE_POSITION_RANGE_PATH = "/hl-wish/ci/scorePosition/noToken/getPosRangeByScore";

    private static final String USER_INFO_BY_TOKEN="/hl-wish/ci/ci_feign/member/noToken/getUserInfoByToken";

    private static final String USER_RIGHTS_BY_USER_ID= "/hl-wish/ci/ci_feign/member/noToken/getUserRightsByMemberId";
    @Autowired
    private GaotuProperties gaotuProperties;

    @Autowired
    private EvidenceLedgerService evidenceLedgerService;

    public Map<String, String> getHeader() {
        Map<String, String> headers = Maps.newHashMap();
        if (!Strings.isNullOrEmpty(gaotuProperties.getEvn())) {
            headers.put("traffic-env", gaotuProperties.getEvn());
        }
        headers.put("content-type", "application/json");
        return headers;
    }

    /**
     * 根据sid换取memberId
     *
     * @param customerId
     * @return
     */
    public Long getMemberId(String customerId) {
        String url = gaotuProperties.getUserUrl() + USER_MEMBER_PATH;
        Map<String, Object> params = Maps.newHashMap();
        params.put("sid", customerId);
        JSONObject res = JsonHttpUtil.get(url, params, getHeader(), new TypeReference<JSONObject>() {
        });

        Integer status = res.getInteger("status");
        if (0 == status) {
            return res.getLong("user_id");
        }
        throw new BusinessException(110, "换取用户ID失败");
    }



    /**
     * 获取主站通用信息，包括高考年份列表。
     */
    public ResponseDTO<CommonInfoResponse> getCommonInfo() {
        String url = gaotuProperties.getZhiyuanUrl() + COMMON_INFO_PATH;
        return JsonHttpUtil.get(url, Maps.newHashMap(), getHeader(), new TypeReference<ResponseDTO<CommonInfoResponse>>() {
        });
    }

    /**
     * 获取成员分数详情
     *
     * @param memberId 成员id
     * @return 成员分数详情
     */
    public ResponseDTO<MemberScoreDetailDTO> getMemberScore(Long memberId, Long formId) {
        String url = gaotuProperties.getZhiyuanUrl() + MEMBER_SCORE_PATH;
        Map<String, Object> params = Maps.newHashMap();
        params.put("memberId", memberId);
        if (formId != null) {
            params.put("formId", formId);
        }
        return JsonHttpUtil.get(url, params, getHeader(), new TypeReference<ResponseDTO<MemberScoreDetailDTO>>() {
        });
    }

    /**
     * 获取批次线数据
     *
     * @param areaId
     * @param prepareType
     * @param subject
     * @return
     */
    public ResponseDTO<BatchDataResponseDTO> getBatchList(Long areaId, String prepareType, String subject) {
        return getBatchList(areaId, prepareType, subject, EvidenceScope.none());
    }

    /**
     * 获取批次线数据，并按权威证据台账签发证据。
     *
     * <p>签发与取数在同一次读取内完成。不要在各个 BizService 里分别接——那会漏，
     * 而且漏掉的那个正好就是不带证据的路径。</p>
     */
    public ResponseDTO<BatchDataResponseDTO> getBatchList(Long areaId, String prepareType, String subject,
                                                          EvidenceScope scope) {
        String url = gaotuProperties.getZhiyuanUrl() + BATCH_LIST_PATH;

        Map<String, Object> params = Maps.newHashMap();
        params.put("areaId", areaId);
        params.put("prepareType", prepareType);
        params.put("subject", subject);
        ResponseDTO<BatchDataResponseDTO> response = JsonHttpUtil.get(url, params, getHeader(), new TypeReference<ResponseDTO<BatchDataResponseDTO>>() {
        });
        attachEvidence(response, EvidenceLedgerService.SOURCE_GAOTU_BATCH_LIST, params, scope);
        return response;
    }

    /**
     * 获取报告信息
     *
     * @param req 报告信息查询请求
     * @return 报告信息
     */
    public ResponseDTO<GetReportInfoDTO> getReportInfo(GetReportInfoReq req) {
        String url = gaotuProperties.getZhiyuanUrl() + REPORT_INFO_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<GetReportInfoDTO>>() {
        });
    }

    /**
     * 获取报告列表
     *
     * @param req 报告列表查询请求
     * @return 报告列表信息
     */
    public ResponseDTO<ListReportInfoDTO> getReportList(ListReportInfoRpcReq req) {
        String url = gaotuProperties.getZhiyuanUrl() + REPORT_LIST_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<ListReportInfoDTO>>() {
        });
    }

    /**
     * 获取志愿方案列表
     *
     * @param req 志愿方案查询请求
     * @return 志愿方案列表
     */
    public ResponseDTO<ProgramPageDTO> getProgramList(ProgramPageReq req) {
        String url = gaotuProperties.getZhiyuanUrl() + PROGRAM_LIST_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<ProgramPageDTO>>() {
        });
    }

    /**
     * 获取志愿方案列表-最新全量
     *
     * @param req 志愿方案查询请求
     * @return 志愿方案列表
     */
    public ResponseDTO<JSONObject> getProgramFullList(ProgramPageReq req) {
        String baseUrl = Strings.isNullOrEmpty(gaotuProperties.getProgramDataUrl()) ? gaotuProperties.getZhiyuanUrl() : gaotuProperties.getProgramDataUrl();
        String url = baseUrl + PROGRAM_LIST_ALL_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<JSONObject>>() {
        });
    }

    public ResponseDTO<JSONObject> getProgramFullListInit(ProgramPageReq req) {
        String baseUrl = Strings.isNullOrEmpty(gaotuProperties.getProgramDataUrl()) ? gaotuProperties.getZhiyuanUrl() : gaotuProperties.getProgramDataUrl();
        String url = baseUrl + PROGRAM_LIST_ALL_INIT_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<JSONObject>>() {
        });
    }

    public ResponseDTO<JSONObject> getProgramFullListPage(ExpertAIProgramPageReq req) {
        String baseUrl = Strings.isNullOrEmpty(gaotuProperties.getProgramDataUrl()) ? gaotuProperties.getZhiyuanUrl() : gaotuProperties.getProgramDataUrl();
        String url = baseUrl + PROGRAM_LIST_ALL_PAGE_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<JSONObject>>() {
        });
    }

    /**
     * 保存志愿方案
     *
     * @param req 志愿方案保存请求
     * @return 是否保存成功
     */
    public ResponseDTO<Long> saveProgramInfo(VolunteerProgramSaveDTO req) {
        String url = gaotuProperties.getZhiyuanUrl() + PROGRAM_SAVE_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<Long>>() {
        });
    }

    /**
     * 机器审核接口
     *
     * @param req 审核请求参数
     * @return 审核结果
     */
    public ResponseDTO<MachineAuditDTO> machineAudit(MachineAuditReq req) {
        String url = gaotuProperties.getRiskUrl() + MACHINE_AUDIT_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<MachineAuditDTO>>() {
        });
    }

    /**
     * 获取推荐方案数量
     *
     * @param req 获取推荐方案数量请求
     * @return 推荐方案数量响应
     */
    public ResponseDTO<RecommendNumResponse> getRecommendProgramNum(RecommendNumReq req) {
        String url = gaotuProperties.getZhiyuanUrl() + RECOMMEND_PROGRAM_NUM_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<RecommendNumResponse>>() {
        });
    }


    /**
     * 删除用户创建分数表
     *
     * @param
     * @return 删除用户创建分数表
     */
    public ResponseDTO<Boolean> deleteUserScoreForm(Long formId, Long memberId) {
        String url = gaotuProperties.getZhiyuanUrl() + DELETE_SCORE_FORM_PATH;
        url = url + "?formId=" + formId + "&memberId=" + memberId;
        return JsonHttpUtil.post(url, Maps.newHashMap(), getHeader(), new TypeReference<ResponseDTO<Boolean>>() {
        });
    }

    /**
     * 删除用户创建分数表
     *
     * @param
     * @return 删除用户创建分数表
     */
    public ResponseDTO<AuthResponseDto> auth(Long memberId) {
        String url = gaotuProperties.getZhiyuanUrl() + AUTH_PATH;
        url = url + "?memberId=" + memberId;
        return JsonHttpUtil.get(url, Maps.newHashMap(), getHeader(), new TypeReference<ResponseDTO<AuthResponseDto>>() {
        });
    }

    /**
     * 查询院校专业方案
     * 输入: 省份、选科、批次、分数、冲稳保数量N
     * 输出: 按照指定的数量N提供用户可以报考的院校专业以及相应的录取率
     *
     * @param req
     * @return
     */
    public ResponseDTO<List<QueryProgramByLimitNumRes>> queryProgramByLimitNum(QueryProgramLimitNumReq req) {
        return queryProgramByLimitNum(req, EvidenceScope.none());
    }

    /**
     * 查询院校专业方案，并按权威证据台账签发证据。
     *
     * <p>签发与取数在同一次读取内完成，见 {@link #getBatchList(Long, String, String, EvidenceScope)}。</p>
     */
    public ResponseDTO<List<QueryProgramByLimitNumRes>> queryProgramByLimitNum(QueryProgramLimitNumReq req,
                                                                              EvidenceScope scope) {
        String url = gaotuProperties.getZhiyuanUrl() + QUERY_PROGRAM_BY_LIMIT_NUM;
        ResponseDTO<List<QueryProgramByLimitNumRes>> response = JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<List<QueryProgramByLimitNumRes>>>() {
        });
        attachEvidence(response, EvidenceLedgerService.SOURCE_GAOTU_PROGRAM_BY_LIMIT_NUM, req, scope);
        return response;
    }

    /**
     * 查询院校专业录取分数
     * 输入: 年份、省份、批次、选科、院校、专业
     * 输出: 对应分数线(如果包含院校专业给出对应每个专业的分数线)
     */
    public ResponseDTO<List<QuerySchoolMajorScoreLineRes>> querySchoolMajorScoreLine(QuerySchoolMajorScoreLineReq req) {
        return querySchoolMajorScoreLine(req, EvidenceScope.none());
    }

    /**
     * 查询院校专业录取分数，并按权威证据台账签发证据。
     *
     * <p>签发与取数在同一次读取内完成，见 {@link #getBatchList(Long, String, String, EvidenceScope)}。</p>
     */
    public ResponseDTO<List<QuerySchoolMajorScoreLineRes>> querySchoolMajorScoreLine(QuerySchoolMajorScoreLineReq req,
                                                                                    EvidenceScope scope) {
        String url = gaotuProperties.getZhiyuanUrl() + QUERY_SCHOOL_MAJOR_SCORE_LINE;
        ResponseDTO<List<QuerySchoolMajorScoreLineRes>> response = JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<List<QuerySchoolMajorScoreLineRes>>>() {
        });
        attachEvidence(response, EvidenceLedgerService.SOURCE_GAOTU_SCHOOL_MAJOR_SCORE_LINE, req, scope);
        return response;
    }

    /**
     * 把查询结果交给台账签发。上游版本、归属范围任一缺失则不签发，
     * 调用方拿不到 evidence 字段，必须按"证据不可用"降级。
     */
    private void attachEvidence(ResponseDTO<?> response, String sourceSystem, Object request, EvidenceScope scope) {
        if (response == null) {
            return;
        }
        ConversationEvidenceDTO evidence = evidenceLedgerService.sign(EvidenceSignRequest.query(
                sourceSystem, response.getDataVersion(), toParams(request), scope));
        if (evidence != null) {
            response.setEvidence(Collections.singletonList(evidence));
        }
    }

    private static Map<String, Object> toParams(Object request) {
        if (request == null) {
            return Collections.emptyMap();
        }
        if (request instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> params = (Map<String, Object>) request;
            return params;
        }
        Map<String, Object> params = JSON.parseObject(JSON.toJSONString(request),
                new TypeReference<Map<String, Object>>() {
                });
        return params == null ? Collections.<String, Object>emptyMap() : params;
    }

    /**
     * 根据分数获取位次范围
     * 输入: 地区ID、科目类型、数据级别、年份、分数
     * 输出: 对应的位次范围信息
     */
    public ResponseDTO<ScorePositionRangeRes> getScorePositionRange(ScorePositionRangeReq req) {
        String url = gaotuProperties.getZhiyuanUrl() + SCORE_POSITION_RANGE_PATH;
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<ScorePositionRangeRes>>() {
        });
    }

    /**
     * 根据token获取用户基本信息
     * @param token
     * @return
     */
    public ResponseDTO<UserInfoByTokenRes> getUserInfoByToken(String token) {
        String url = gaotuProperties.getZhiyuanUrl() + USER_INFO_BY_TOKEN;
       Map<String,Object>req= Maps.newHashMap();
        req.put("userIdToken",token);
        return JsonHttpUtil.get(url, req, getHeader(), new TypeReference<ResponseDTO<UserInfoByTokenRes>>() {
        });
    }

    /**
     * *获取用户权益
     *
     * @param memberId
     * @return
     */
    public ResponseDTO<UserRightsByUserIdRes> getUserRights(String memberId) {
        String url = gaotuProperties.getZhiyuanUrl() + USER_RIGHTS_BY_USER_ID;
        Map<String,String>req= Maps.newHashMap();
        req.put("memberId",memberId);
        return JsonHttpUtil.post(url, req, getHeader(), new TypeReference<ResponseDTO<UserRightsByUserIdRes>>() {
        });
    }


}
