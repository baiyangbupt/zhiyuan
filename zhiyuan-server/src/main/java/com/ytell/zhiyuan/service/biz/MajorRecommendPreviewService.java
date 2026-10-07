package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.inner.MajorRecommendPreviewReq;
import com.ytell.zhiyuan.model.dto.inner.MajorRecommendPreviewRes;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.function.Function;

/**
 * 专业方向推荐预览（只读纵切）。
 *
 * <p>存在的理由：Agent 的只读工具面里，"专业方向"这一层一直没有入口——
 * 模型只能查院校/专业目录与历年录取，回答"我适合什么专业方向"时要么用记忆、
 * 要么绕到志愿候选（那是**具体志愿单元**，不是专业方向）。这里把 Java 侧真实存在
 * 的专业推荐（会话画像 → rank 服务专业级打分 → Top8）以**只读**方式暴露出来。</p>
 *
 * <p>三条纪律（每条都是评审点）：</p>
 * <ol>
 *   <li><b>不写</b>：只读会话画像 + 调 {@code ChatSessionBizService#recommendMajor}
 *       （它只做 rank 打分与 Top8 裁剪），不落库、不 bump 版本、不签发证据
 *       （推荐分是算法产物，不是观测事实）。</li>
 *   <li><b>缺画像不造数</b>：无档案/无分数/画像缺 rank 必读字段时回
 *       {@code code=0, data=null, msg=<原因码>}——"没有推荐"与"调不动"必须分得开，
 *       编一份热度榜顶替是最坏的一种"可用"。</li>
 *   <li><b>只见一页</b>：{@link #MAX_TOP_N} 是硬上限，超了截断不报错；
 *       综合分降序的 topN 是**切片**，不是全量专业榜。</li>
 * </ol>
 */
@Slf4j
@Service
public class MajorRecommendPreviewService {

    /** 默认条数 = 硬上限：与 rank 侧 topN=8 的口径一致（{@code ChatSessionBizService#recommendMajor} 取 8）。 */
    public static final int MAX_TOP_N = 8;

    /** 无档案：会话还没有 userScoreDetail 行（空会话就是这样）。 */
    public static final String REASON_PROFILE_MISSING = "session_profile_missing";

    /** 无分数：档案行存在但没有总分。 */
    public static final String REASON_SCORE_MISSING = "session_score_missing";

    /**
     * 画像缺 rank 算法必读字段：缺了调用只会**静默**变成空列表
     * （rank 侧 500 → {@code callRecommendSubMajor} 降级空表），
     * 于是"没有推荐"与"输入不齐调不动"分不开。缺项名跟在冒号后面。
     */
    public static final String REASON_PROFILE_INCOMPLETE_PREFIX = "session_profile_incomplete:";

    /** 打分跑通但一条都没有（如优势学科与专业数据没有交集）：如实标注，不当成错误。 */
    public static final String LIMITATION_EMPTY = "major_recommend_empty";

    @Autowired
    private ChatSessionBizService chatSessionBizService;

    public ResponseDTO<MajorRecommendPreviewRes> preview(MajorRecommendPreviewReq req) {
        if (req == null || req.getChatSessionId() == null) {
            throw new BusinessException(110, "chatSessionId 缺失");
        }
        Long chatSessionId = req.getChatSessionId();
        int topN = resolveTopN(req.getTopN());

        // 空会话没有 userScoreDetail 行：读取按"没有"处理（不抛 404），如实回原因。
        CreateSessionReq profile = chatSessionBizService.loadSessionScoreDetail(chatSessionId);
        if (profile == null) {
            return unavailable(REASON_PROFILE_MISSING);
        }
        if (profile.getTotalScore() == null) {
            return unavailable(REASON_SCORE_MISSING);
        }
        List<String> missing = missingRankInputs(profile);
        if (!missing.isEmpty()) {
            return unavailable(REASON_PROFILE_INCOMPLETE_PREFIX + String.join(",", missing));
        }

        // 只读：rank 打分（内部已按 8 裁剪），这里再按请求 topN 裁一次。
        List<RecommendSubMajorResponse.MajorRecommendItem> items =
                chatSessionBizService.recommendMajor(profile);
        if (items == null) {
            items = Lists.newArrayList();
        }
        List<RecommendSubMajorResponse.MajorRecommendItem> trimmed =
                items.size() > topN ? Lists.newArrayList(items.subList(0, topN)) : items;

        MajorRecommendPreviewRes data = new MajorRecommendPreviewRes();
        data.setChatSessionId(chatSessionId);
        data.setTopN(topN);
        data.setItems(trimmed);
        data.setLimitations(Lists.newArrayList());
        if (trimmed.isEmpty()) {
            data.getLimitations().add(LIMITATION_EMPTY);
        }

        ResponseDTO<MajorRecommendPreviewRes> result = new ResponseDTO<MajorRecommendPreviewRes>();
        result.setCode(0);
        result.setMsg("ok");
        result.setData(data);
        return result;
    }

    /**
     * 不可用：{@code data=null} + 原因码（{@code msg}）。
     *
     * <p>业务码仍是 0——"没有这份画像"不是查询失败；调用方（Agent 工具）据此
     * 如实说"不可用 + 原因"，而不是把空数据当"没有可推荐的专业方向"。</p>
     */
    private ResponseDTO<MajorRecommendPreviewRes> unavailable(String reason) {
        ResponseDTO<MajorRecommendPreviewRes> result = new ResponseDTO<MajorRecommendPreviewRes>();
        result.setCode(0);
        result.setMsg(reason);
        result.setData(null);
        return result;
    }

    private int resolveTopN(Integer topN) {
        if (topN == null || topN < 1) {
            return MAX_TOP_N;
        }
        return Math.min(topN, MAX_TOP_N);
    }

    /**
     * rank {@code recommend_submajor} 的**必读字段**。
     *
     * <p>它一上来就取 {@code studentinfo['batch']['level']} 与 {@code strengthSubjectList}，
     * 缺任一项都会 500；而 Java 侧的 {@code callRecommendSubMajor} 把异常降级成空列表，
     * "算法没命中"和"输入不齐"就变成同一个空结果。既然这里能看出来，就先挡住、
     * 把缺项如实报出去——不替用户补，也不假装推荐过了。</p>
     */
    private List<String> missingRankInputs(CreateSessionReq profile) {
        List<String> missing = Lists.newArrayList();
        if (profile.getBatch() == null || Strings.isNullOrEmpty(profile.getBatch().getLevel())) {
            missing.add("batchLevel");
        }
        if (profile.getSubjectType() == null || Strings.isNullOrEmpty(profile.getSubjectType().getDesc())) {
            missing.add("subjectType");
        }
        if (profile.getSex() == null || Strings.isNullOrEmpty(profile.getSex().getCode())) {
            missing.add("sex");
        }
        if (!hasItemWithName(profile.getSubjectList(), CreateSessionReq.SubjectItem::getName)) {
            missing.add("subjectList");
        }
        if (!hasItemWithName(profile.getStrengthSubjectList(), CreateSessionReq.SubjectScore::getSubjectName)) {
            missing.add("strengthSubjectList");
        }
        return missing;
    }

    private <T> boolean hasItemWithName(List<T> items, Function<T, String> namer) {
        if (items == null) {
            return false;
        }
        for (T item : items) {
            if (item != null && !Strings.isNullOrEmpty(namer.apply(item))) {
                return true;
            }
        }
        return false;
    }
}
