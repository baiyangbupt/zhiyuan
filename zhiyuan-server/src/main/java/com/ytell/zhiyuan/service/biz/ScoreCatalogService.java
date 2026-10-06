package com.ytell.zhiyuan.service.biz;

import cn.hutool.core.collection.CollectionUtil;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.gaotu.BatchDataResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.SubjectPolicyResponseDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 补录成绩要用的两张**编码表**（批次 / 科目）。
 *
 * <p>2026-10-06 的事故根因之一：模型手里只有分数，没有编码——它把
 * {@code subjectScoreList} 出成 {@code [{"score":88},{"score":85}]}，合并后
 * {@code subject=null} 一路流到组查询串的地方炸掉；批次同理（"本科批"这种名字上游
 * 不报错、只返回空）。这里把"人话 ↔ 编码"的对照做成**只读工具的后端**：
 * 模型在出卡之前先查这一份，再补齐编码。</p>
 *
 * <p>数据来源与前端 {@code ScoreUpdateSupplement} 完全同源：选科策略
 * {@code /selectSubjectPolicy/noToken/subjectPolicy} + 批次线
 * {@code /batchData/anno/batchListByPolicy}。批次是**观测**（行为按批次线签发证据），
 * 选科策略是**字典**（不签证据，理由同 {@code getPlanMajorFilterList}）。</p>
 */
@Slf4j
@Service
public class ScoreCatalogService {

    /**
     * 选考科目：上游选科策略回的就是这一套（07 技术仅浙江有，以上游为准）。
     * 组查询串（{@code ProgramPageReq.subjects}）只认这一套。
     */
    public static final List<String[]> ELECTIVE_SUBJECTS = Lists.newArrayList(
            new String[]{"01", "物理"},
            new String[]{"02", "历史"},
            new String[]{"03", "政治"},
            new String[]{"04", "地理"},
            new String[]{"05", "化学"},
            new String[]{"06", "生物"},
            new String[]{"07", "技术"});

    /**
     * 语数外：上游选科策略**只回选考科目**，三门主科不在其中（浙江实测），
     * 而它们的编码（08/10/11）是补录各科的合法取值，必须由业务侧补全。
     * 与 {@code FlowConfigService.addFixedSubjects} 是同一套编码。
     */
    public static final List<String[]> MAIN_SUBJECTS = Lists.newArrayList(
            new String[]{"08", "语文"},
            new String[]{"10", "数学"},
            new String[]{"11", "英语"});

    /**
     * 主科编码：**不参与组查询串**（{@code toProgramQuery} 的 forbiddenList 就是这三个）。
     */
    public static final List<String> MAIN_SUBJECT_CODES = Lists.newArrayList("08", "10", "11");

    /**
     * 标准科目编码全集 = 选考科目（01-07）∪ 语数外（08/10/11）。
     *
     * <p>边界口径与 {@code toProgramQuery} 的 forbiddenList（08/10/11 不进组查询串）
     * 一致：那边是"哪些码不参与组查询"的排除写法，这里是"哪些码是标准码"的包含写法；
     * 两份都从同一套编码标准导出（见静态初始化块）。</p>
     */
    public static final List<String> STANDARD_SUBJECT_CODES;

    private static final Set<String> STANDARD_SUBJECT_CODE_SET;
    private static final Map<String, String> SUBJECT_NAMES;

    static {
        List<String> codes = Lists.newArrayList();
        Map<String, String> names = new LinkedHashMap<String, String>();
        for (String[] item : ELECTIVE_SUBJECTS) {
            codes.add(item[0]);
            names.put(item[0], item[1]);
        }
        for (String[] item : MAIN_SUBJECTS) {
            codes.add(item[0]);
            names.put(item[0], item[1]);
        }
        STANDARD_SUBJECT_CODES = java.util.Collections.unmodifiableList(codes);
        STANDARD_SUBJECT_CODE_SET = java.util.Collections.unmodifiableSet(new HashSet<String>(codes));
        SUBJECT_NAMES = java.util.Collections.unmodifiableMap(names);
    }

    public static boolean isStandardSubjectCode(String code) {
        return code != null && STANDARD_SUBJECT_CODE_SET.contains(code.trim());
    }

    /** 标准编码 → 人读名称（卡上展示用）；非标准码回 null，不编名字。 */
    public static String subjectNameFor(String code) {
        return code == null ? null : SUBJECT_NAMES.get(code.trim());
    }

    /**
     * 从各科成绩里取**选考科目编码**（升序、去重外的原样保留），给组查询串用。
     *
     * <p>两层防御：空元素/null 码直接跳过（2026-10-06 的 NPE 就在这里——`stream` 的
     * `filter/map` 遇到 null 元素或 null 码会把 {@code Joiner} 炸掉），非标准码不收
     * （拼进查询串只会让上游返回空，看起来像"没有数据"）。取不到任何编码时由调用方
     * 回清晰的 110，而不是拿空串去查。</p>
     */
    public static List<String> electiveSubjectCodes(List<CreateSessionReq.SubjectScore> list) {
        List<String> codes = Lists.newArrayList();
        Set<String> seen = new HashSet<String>();
        if (list == null) {
            return codes;
        }
        for (CreateSessionReq.SubjectScore item : list) {
            if (item == null || Strings.isNullOrEmpty(item.getSubject())) {
                continue;
            }
            String code = item.getSubject().trim();
            if (MAIN_SUBJECT_CODES.contains(code) || !isElectiveSubjectCode(code) || !seen.add(code)) {
                continue;
            }
            codes.add(code);
        }
        java.util.Collections.sort(codes);
        return codes;
    }

    public static boolean isElectiveSubjectCode(String code) {
        if (code == null) {
            return false;
        }
        String trimmed = code.trim();
        for (String[] item : ELECTIVE_SUBJECTS) {
            if (item[0].equals(trimmed)) {
                return true;
            }
        }
        return false;
    }

    @Autowired
    private GaotuClient gaotuClient;

    /**
     * 批次线字典：`[{code, name, level, score, pos}]`。
     *
     * <p>{@code level} 是**本专科的编码**（01 本科 / 02 专科）——建档策略缓存
     * （{@code ProvinceVolunteerStrategyManager}）就是按 `provinceCode + level` 取的，
     * 传"本科"这种名字会静默取不到策略。这正是前端
     * {@code buildCreateSessionBatchPayload} 的取值口径。</p>
     *
     * <p>科类（{@code subject} 查询参数）与批次线不是一套编码：浙江是 N（综合）、
     * 江苏是 WL/LS。调用方可以给科类码，也可以给选考科目码/名称（如"01"/"物理"），
     * 这里按选科策略把它翻译成对应科类；该省有多个科类而又没给时，**拒绝并报清单**，
     * 不替用户挑一个（挑错等于拿错科类的批次线去建会话）。</p>
     */
    public ResponseDTO<List<Map<String, Object>>> listBatchOptions(Long areaId, String subjectType,
                                                                   EvidenceScope scope) {
        if (areaId == null) {
            throw new BusinessException(110, "请先提供省份编码");
        }
        String area = String.valueOf(areaId);
        SubjectPolicyResponseDTO policy = requirePolicy(gaotuClient.getSubjectPolicy(area), area);
        String prepareType = policy.getPrepareType() == null ? null : policy.getPrepareType().getCode();
        if (Strings.isNullOrEmpty(prepareType)) {
            throw new BusinessException(110, "该省份暂无填报策略，无法读取批次线");
        }
        String subject = resolveSubjectType(policy, subjectType, area);

        ResponseDTO<BatchDataResponseDTO> response = gaotuClient.getBatchList(areaId, prepareType, subject, scope);
        if (response == null || (response.getCode() != null && response.getCode() != 0)) {
            log.warn("listBatchOptions upstream rejected: areaId={} prepareType={} subject={} code={} msg={}",
                    area, prepareType, subject,
                    response == null ? null : response.getCode(), response == null ? null : response.getMsg());
            throw new BusinessException(110, "批次线查询失败，请确认科类编码是否正确");
        }
        BatchDataResponseDTO data = response.getData();
        List<Map<String, Object>> options = Lists.newArrayList();
        if (data != null && CollectionUtil.isNotEmpty(data.getBatchList())) {
            for (BatchDataResponseDTO.BatchInfo item : data.getBatchList()) {
                if (item == null || Strings.isNullOrEmpty(item.getBatch())) {
                    continue;
                }
                Map<String, Object> option = new LinkedHashMap<String, Object>();
                option.put("code", item.getBatch());
                option.put("name", item.getBatchTitle());
                option.put("level", item.getLevel() == null ? null : item.getLevel().getKey());
                option.put("score", parseScore(item.getScore()));
                if (item.getPos() != null) {
                    option.put("pos", item.getPos());
                }
                options.add(option);
            }
        }
        if (options.isEmpty()) {
            throw new BusinessException(110, "未查询到该省份的批次线数据");
        }
        ResponseDTO<List<Map<String, Object>>> result = new ResponseDTO<List<Map<String, Object>>>();
        result.setCode(0);
        result.setMsg("ok");
        result.setData(options);
        // 批次是**观测**（批次线/位次），证据随取数一起签发（与 /batch/info 同源同口径）。
        result.setEvidence(response.getEvidence());
        return result;
    }

    /**
     * 科目编码字典：`[{code, name}]`，选考科目（01-07）+ 语数外（08/10/11）。
     *
     * <p>给模型的是**人话 ↔ 编码**的完整对照：用户说"化学 82"，模型要能自己落到
     * {@code {"subject":"05","score":82}}；只说分数不出编码的草稿，会在合并后炸在下游。</p>
     */
    public ResponseDTO<List<Map<String, Object>>> listSubjectOptions(Long areaId) {
        if (areaId == null) {
            throw new BusinessException(110, "请先提供省份编码");
        }
        String area = String.valueOf(areaId);
        SubjectPolicyResponseDTO policy = requirePolicy(gaotuClient.getSubjectPolicy(area), area);
        List<Map<String, Object>> options = Lists.newArrayList();
        Set<String> seen = new HashSet<String>();
        if (CollectionUtil.isNotEmpty(policy.getSubjectList())) {
            for (SubjectPolicyResponseDTO.SubjectOption item : policy.getSubjectList()) {
                if (item == null || Strings.isNullOrEmpty(item.getSubject()) || !seen.add(item.getSubject())) {
                    continue;
                }
                Map<String, Object> option = new LinkedHashMap<String, Object>();
                option.put("code", item.getSubject());
                option.put("name", item.getSubjectName());
                options.add(option);
            }
        }
        for (String[] main : MAIN_SUBJECTS) {
            if (!seen.add(main[0])) {
                continue;
            }
            Map<String, Object> option = new LinkedHashMap<String, Object>();
            option.put("code", main[0]);
            option.put("name", main[1]);
            options.add(option);
        }
        if (options.isEmpty()) {
            throw new BusinessException(110, "未查询到该省份的选科编码");
        }
        ResponseDTO<List<Map<String, Object>>> result = new ResponseDTO<List<Map<String, Object>>>();
        result.setCode(0);
        result.setMsg("ok");
        result.setData(options);
        // 字典不签发证据：能引用的是"这个省有哪些科目码"这件事本身，不是一条观测事实。
        return result;
    }

    /**
     * 补录草稿缺项时**能从省策略推导出来**的那部分缺省：科类 + 填报类型。
     *
     * <p>科类只取"该省唯一"的情形（浙江 N/综合）；多科类省份（江苏 WL/LS）不替用户挑，
     * 保持调用方原有的 110。填报类型直接取策略的 `prepareType`——这正是**前端口径**：
     * 表单（`ScoreSupplement`：`policy.prepareType.code`）与建会话
     * （`customerDetailSession`：`policyRes.data.prepareType`）都拿它当 prepareType，
     * 批次线查询也用它；缺省落到 VOLUNTEER 只在策略也不给时才发生。</p>
     *
     * <p>上游取不到/无策略一律回 null，调用方保持各自原兜底，校验不放宽。</p>
     */
    public ProvinceDefaults provinceDefaultsOrNull(String provinceCode) {
        if (Strings.isNullOrEmpty(provinceCode)) {
            return null;
        }
        try {
            SubjectPolicyResponseDTO policy = requirePolicy(
                    gaotuClient.getSubjectPolicy(provinceCode.trim()), provinceCode.trim());
            ProvinceDefaults defaults = new ProvinceDefaults();
            defaults.setSubjectType(uniqueSubjectTypeOrNull(policy));
            defaults.setPrepareType(prepareTypeOrNull(policy));
            return defaults;
        } catch (Exception e) {
            log.warn("provinceDefaultsOrNull failed, provinceCode={}", provinceCode, e);
            return null;
        }
    }

    /** 该省策略里的唯一科类；没有/多科类/编码为空一律 null（不替用户挑）。 */
    private CreateSessionReq.SubjectType uniqueSubjectTypeOrNull(SubjectPolicyResponseDTO policy) {
        List<SubjectPolicyResponseDTO.SubjectTypeOption> types = policy.getSubjectTypeList();
        if (CollectionUtil.isEmpty(types) || types.size() != 1) {
            return null;
        }
        SubjectPolicyResponseDTO.SubjectTypeOption only = types.get(0);
        if (only == null || Strings.isNullOrEmpty(only.getCode())) {
            return null;
        }
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode(only.getCode());
        subjectType.setDesc(only.getDesc());
        return subjectType;
    }

    /** 省策略的填报类型（PREDICT 模拟填报 / VOLUNTEER 智能填报）；缺编码回 null。 */
    private CreateSessionReq.PrepareType prepareTypeOrNull(SubjectPolicyResponseDTO policy) {
        BatchDataResponseDTO.TypeInfo prepareType = policy.getPrepareType();
        if (prepareType == null || Strings.isNullOrEmpty(prepareType.getCode())) {
            return null;
        }
        CreateSessionReq.PrepareType result = new CreateSessionReq.PrepareType();
        result.setCode(prepareType.getCode());
        result.setDesc(prepareType.getDesc());
        return result;
    }

    /** 单次策略查询能推导出的补录缺省（见 {@link #provinceDefaultsOrNull}）。 */
    public static class ProvinceDefaults {
        private CreateSessionReq.SubjectType subjectType;
        private CreateSessionReq.PrepareType prepareType;

        public CreateSessionReq.SubjectType getSubjectType() {
            return subjectType;
        }

        public void setSubjectType(CreateSessionReq.SubjectType subjectType) {
            this.subjectType = subjectType;
        }

        public CreateSessionReq.PrepareType getPrepareType() {
            return prepareType;
        }

        public void setPrepareType(CreateSessionReq.PrepareType prepareType) {
            this.prepareType = prepareType;
        }
    }

    private SubjectPolicyResponseDTO requirePolicy(ResponseDTO<SubjectPolicyResponseDTO> response, String area) {
        if (response == null || (response.getCode() != null && response.getCode() != 0)
                || response.getData() == null) {
            log.warn("subject policy unavailable: areaId={} code={} msg={}",
                    area, response == null ? null : response.getCode(),
                    response == null ? null : response.getMsg());
            throw new BusinessException(110, "未查询到该省份的选科策略");
        }
        return response.getData();
    }

    /** 科类解析：显式科类码 > 选考科目码/名称翻译 > 唯一科类兜底；多科类且没给 → 拒绝并报清单。 */
    private String resolveSubjectType(SubjectPolicyResponseDTO policy, String requested, String area) {
        List<SubjectPolicyResponseDTO.SubjectTypeOption> types = policy.getSubjectTypeList();
        String trimmed = Strings.isNullOrEmpty(requested) ? null : requested.trim();
        if (trimmed != null) {
            if (types != null) {
                for (SubjectPolicyResponseDTO.SubjectTypeOption item : types) {
                    if (item != null && trimmed.equals(item.getCode())) {
                        return item.getCode();
                    }
                }
            }
            // 给了选考科目（"01"/"物理"）时翻译成该科目的科类（江苏 01→WL），
            // 拿不到就原样交给上游——错了由上面的 code!=0 分支回一句清晰的 110。
            String translated = subjectTypeOfElective(policy, trimmed);
            return translated == null ? trimmed : translated;
        }
        if (CollectionUtil.isNotEmpty(types)) {
            if (types.size() == 1) {
                return types.get(0).getCode();
            }
            List<String> codes = Lists.newArrayList();
            for (SubjectPolicyResponseDTO.SubjectTypeOption item : types) {
                if (item != null && !Strings.isNullOrEmpty(item.getCode())) {
                    codes.add(item.getCode());
                }
            }
            throw new BusinessException(110, "该省份有多个科类（" + String.join("/", codes)
                    + "），请先指定科类后再读取批次线");
        }
        throw new BusinessException(110, "该省份未提供科类列表，无法读取批次线");
    }

    private String subjectTypeOfElective(SubjectPolicyResponseDTO policy, String requested) {
        if (CollectionUtil.isEmpty(policy.getSubjectList())) {
            return null;
        }
        for (SubjectPolicyResponseDTO.SubjectOption item : policy.getSubjectList()) {
            if (item == null) {
                continue;
            }
            boolean matched = requested.equals(item.getSubject())
                    || (!Strings.isNullOrEmpty(item.getSubjectName()) && requested.equals(item.getSubjectName()));
            if (matched) {
                return Strings.isNullOrEmpty(item.getSubjectType()) ? null : item.getSubjectType();
            }
        }
        return null;
    }

    /** 上游的分数线是四位小数字符串（"494.0000"）；给人看的形状是 494。 */
    private Number parseScore(String raw) {
        if (Strings.isNullOrEmpty(raw)) {
            return null;
        }
        try {
            BigDecimal value = new BigDecimal(raw.trim()).stripTrailingZeros();
            if (value.scale() <= 0) {
                return value.longValueExact();
            }
            return value.doubleValue();
        } catch (ArithmeticException | NumberFormatException e) {
            log.warn("unparseable batch score: {}", raw);
            return null;
        }
    }
}
