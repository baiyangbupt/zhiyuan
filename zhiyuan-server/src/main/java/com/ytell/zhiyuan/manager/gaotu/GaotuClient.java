package com.ytell.zhiyuan.manager.gaotu;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.alibaba.fastjson.TypeReference;
import com.google.common.base.Strings;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.config.GaotuProperties;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.EvidenceContentDigest;
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
    /**
     * 选科策略（含**科目编码字典**与科类列表）。与前端
     * `sessionDetail.ts::getSubjectPolicy` 打的是同一条上游。
     */
    private static final String SUBJECT_POLICY_PATH = "/hl-wish/ci/selectSubjectPolicy/noToken/subjectPolicy";
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

    /**
     * 招生计划查询。上游在 `SchoolH5Controller` 的 `/h5/school` 下，同样经 `/hl-wish/ci` 网关。
     *
     * <p>**完整前缀未经真实调用验证**：本仓现有路径都是 `/hl-wish/ci/ci_feign/...`，
     * 而这条属于另一个 controller。第一次真机联调时先确认前缀，别把 404 当成"上游没这功能"。
     */
    private static final String PLAN_MAJOR_DATA_LIST = "/hl-wish/ci/h5/school/noToken/planMajorDataList";

    /** 招生计划的筛选条件树（年份/科类/批次/招生单元）。实测可用，免 token。 */
    private static final String PLAN_MAJOR_FILTER_LIST_PATH = "/hl-wish/ci/h5/school/noToken/planMajorFilterList";

    /** 招生章程（院校资讯里的招生简章全文）。与下面那条 SCHOOL_RULE 不是一回事。 */
    private static final String SCHOOL_NEWS_PAGE_PATH = "/hl-wish/ci/h5/school/noToken/newsPage";
    private static final String SCHOOL_NEWS_INFO_PATH = "/hl-wish/ci/h5/school/noToken/getNewsInfo";

    /** 学校招生章程（**展示文案**，见 SchoolRuleRes 的说明）。 */
    private static final String SCHOOL_RULE_PATH = "/hl-wish/ci/school/noToken/getSchoolRule";
    
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
     * 选科策略：该省的**科目编码字典** + 科类列表 + 填报方式。
     *
     * <p>不签发证据：它与批次字典同属**枚举字典**（"这张表有哪些格子"），不是观测到的
     * 招生事实（"格子里是什么"）。给字典签证据会让下游把"编码表长这样"当成一条可引用的
     * 权威观测。</p>
     */
    public ResponseDTO<SubjectPolicyResponseDTO> getSubjectPolicy(String areaId) {
        String url = gaotuProperties.getZhiyuanUrl() + SUBJECT_POLICY_PATH;
        Map<String, Object> params = Maps.newHashMap();
        params.put("areaId", areaId);
        return JsonHttpUtil.get(url, params, getHeader(),
                new TypeReference<ResponseDTO<SubjectPolicyResponseDTO>>() {
                });
    }

    /**
     * 院校资讯列表（招生章程/招生简章）。免 token，**免分数**。
     *
     * <p>不签发证据：列表只有标题与时间，是**索引**不是内容。证据挂在详情那次读取上
     * （见 {@link #getSchoolNewsDetail}）——给索引签证据会让"引用了章程原文"变成
     * "引用了一个标题"。</p>
     */
    public ResponseDTO<SchoolNewsRes.Page> getSchoolNewsPage(String schoolId, Integer current, Integer size) {
        String url = gaotuProperties.getZhiyuanUrl() + SCHOOL_NEWS_PAGE_PATH;
        Map<String, Object> body = Maps.newHashMap();
        body.put("current", current == null ? 1 : current);
        body.put("size", size == null ? 20 : size);
        Map<String, Object> model = Maps.newHashMap();
        model.put("schoolId", schoolId);
        body.put("model", model);
        return JsonHttpUtil.post(url, body, getHeader(),
                new TypeReference<ResponseDTO<SchoolNewsRes.Page>>() {
                });
    }

    /**
     * 招生章程正文，并按权威证据台账签发证据。
     *
     * <p>这是**原文条款**那条来源：学校发布、平台收录，标题自带年份、有上下架标志。
     * 与 {@link #getSchoolRule}（录取规则摘要，没规则时回占位文案）区分开——
     * 后者**不签发证据**。</p>
     */
    public ResponseDTO<SchoolNewsRes> getSchoolNewsDetail(Long newsId, EvidenceScope scope) {
        String url = gaotuProperties.getZhiyuanUrl() + SCHOOL_NEWS_INFO_PATH;
        Map<String, Object> params = Maps.newHashMap();
        params.put("id", newsId);
        ResponseDTO<SchoolNewsRes> response = JsonHttpUtil.get(url, params, getHeader(),
                new TypeReference<ResponseDTO<SchoolNewsRes>>() {
                });
        attachEvidence(response, EvidenceLedgerService.SOURCE_GAOTU_SCHOOL_NEWS, params, scope);
        return response;
    }

    /**
     * 招生计划的筛选条件树：年份 → 科类 → 批次 → **招生单元**。
     *
     * <p>这是"专业级"那条链的**入口**：末层的 {@code value} 是 {@code schoolUnitId}，
     * 而 {@link #queryPlanMajorData} 反过来要求它。没有这一步，招生计划与
     * 专业级录取数据都没有门可入——而它是**免分数**的。
     *
     * <p>不签发证据：它是**字典**（枚举可选值），不是观测到的招生事实。
     * 给它签证据会把"这张表有哪些格子"与"格子里是什么"混成一类。</p>
     */
    public ResponseDTO<List<PlanMajorFilterNode>> getPlanMajorFilterList(String schoolId, String areaId) {
        String url = gaotuProperties.getZhiyuanUrl() + PLAN_MAJOR_FILTER_LIST_PATH;
        Map<String, Object> params = Maps.newHashMap();
        params.put("schoolId", schoolId);
        params.put("areaId", areaId);
        return JsonHttpUtil.get(url, params, getHeader(),
                new TypeReference<ResponseDTO<List<PlanMajorFilterNode>>>() {
                });
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
     * 查询学校招生章程。
     *
     * <p><b>不是原文条款的可靠来源</b>：该校没有规则时上游回占位文案，且响应无标志位。
     * 这里**不签发证据**——它不是取数结果，而是一段展示文案；给它签证据等于
     * 把"我们查过数仓"的权威性借给一段可能只是"正在更新中"的文本。
     */
    public ResponseDTO<SchoolRuleRes> getSchoolRule(Long schoolId) {
        String url = gaotuProperties.getZhiyuanUrl() + SCHOOL_RULE_PATH;
        Map<String, Object> query = new java.util.HashMap<String, Object>();
        query.put("schoolId", schoolId);
        return JsonHttpUtil.get(url, query, getHeader(),
                new TypeReference<ResponseDTO<SchoolRuleRes>>() {
                });
    }

    /**
     * 批量查询招生计划。
     *
     * <p>与分数线一样按**身份**取数（入参不含分数）：这是"能回答任意院校专业"
     * 的依据。分数带限制只属于候选推荐那条端点。
     */
    public ResponseDTO<List<PlanMajorDataRes>> queryPlanMajorData(QueryPlanMajorDataReq req) {
        return queryPlanMajorData(req, EvidenceScope.none());
    }

    /**
     * 批量查询招生计划，并按权威证据台账签发证据。
     */
    public ResponseDTO<List<PlanMajorDataRes>> queryPlanMajorData(QueryPlanMajorDataReq req,
                                                                  EvidenceScope scope) {
        String url = gaotuProperties.getZhiyuanUrl() + PLAN_MAJOR_DATA_LIST;
        ResponseDTO<List<PlanMajorDataRes>> response = JsonHttpUtil.post(url, req, getHeader(),
                new TypeReference<ResponseDTO<List<PlanMajorDataRes>>>() {
                });
        attachEvidence(response, EvidenceLedgerService.SOURCE_GAOTU_PLAN_MAJOR_DATA, req, scope);
        return response;
    }

    /**
     * 把查询结果交给台账签发。响应内容（data 摘要）、归属范围任一缺失则不签发，
     * 调用方拿不到 evidence 字段，必须按"证据不可用"降级。
     */
    private void attachEvidence(ResponseDTO<?> response, String sourceSystem, Object request, EvidenceScope scope) {
        if (response == null) {
            return;
        }
        // "数据版本"取 data 内容本身的摘要，不取上游信封字段——上游信封上没有版本字段，
        // 且信封里的 timestamp 逐次调用都变。见 EvidenceContentDigest。
        String dataVersion = EvidenceContentDigest.digest(response.getData());
        ConversationEvidenceDTO evidence = evidenceLedgerService.sign(EvidenceSignRequest.query(
                sourceSystem, dataVersion, toParams(request), scope));
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
