package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ScoreUpdatePreviewDTO;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 补录各科的**编码校验**（2026-10-06 真事故的回归护栏）：
 *
 * <p>模型出过 `subjectScoreList=[{"score":88},{"score":85}]`（只有分数、没有科目编码），
 * 合并后 `subject=null` 一路流到组查询串拼接处才炸（NPE → 回包 `code:-1 message:null`，
 * 用户只看到"失败"两个字）。现在这类草稿必须在**落库之前**以 110「非标准选科编码」被挡下，
 * 两个入口一致：执行（确认链真正落库那条，`updateScoreDetailForUser`）与预览
 * （用户还没点确认的那条，`previewScoreUpdate`）。</p>
 */
public class ChatSessionBizServiceScoreUpdateSubjectCodeTest {

    private ChatSessionBizService service;

    @BeforeEach
    void setUp() {
        service = new ChatSessionBizService();
        ConversationAccessService conversationAccessService = mock(ConversationAccessService.class);
        when(conversationAccessService.requireSessionUserId(1L, 2L)).thenReturn(7L);
        ReflectionTestUtils.setField(service, "conversationAccessService", conversationAccessService);
        // 空会话：没有既有的 userScoreDetail 行。
        ChatSessionExtraDataSharedService extraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", extraDataSharedService);

        // 编码校验之后的权益校验放行：拒绝用例根本走不到这里（先被 110 拦），
        // 绿路径用例用它证明"标准编码没有被误伤"。
        UserBizService userBizService = mock(UserBizService.class);
        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(Boolean.TRUE);
        when(userBizService.checkRights(any(), any(), any())).thenReturn(rights);
        ReflectionTestUtils.setField(service, "userBizService", userBizService);

        PlanningStateService planningStateService = mock(PlanningStateService.class);
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(2L);
        state.setVersion(5);
        when(planningStateService.getPlanningState(2L)).thenReturn(state);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);

        // 补录缺省（科类/填报类型）从省策略推导——本类用例的草稿自带科类、只缺填报类型，
        // 桩回 null（= 推导不出来），保持各用例原有的校验/兜底行为（缺 prepareType 走默认 VOLUNTEER）。
        ReflectionTestUtils.setField(service, "scoreCatalogService", mock(ScoreCatalogService.class));
    }

    @Test
    void nullElementIsRejectedWith110BeforeAnyWrite() {
        CreateSessionReq req = baseRequest();
        req.setSubjectScoreList(Lists.newArrayList((CreateSessionReq.SubjectScore) null));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.updateScoreDetailForUser(1L, 2L, req, 7L));

        assertEquals(110, error.getStatus());
        assertEquals("非标准选科编码", error.getMessage());
    }

    @Test
    void scoreOnlyElementWithoutSubjectCodeIsRejectedWith110() {
        CreateSessionReq req = baseRequest();
        CreateSessionReq.SubjectScore score = new CreateSessionReq.SubjectScore();
        score.setScore(88);
        CreateSessionReq.SubjectScore second = new CreateSessionReq.SubjectScore();
        second.setScore(85);
        req.setSubjectScoreList(Lists.newArrayList(score, second));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.updateScoreDetailForUser(1L, 2L, req, 7L));

        assertEquals(110, error.getStatus(),
                "2026-10-06 的原始事故形状：只有分数、没有科目编码");
        assertEquals("非标准选科编码", error.getMessage());
    }

    @Test
    void nonStandardSubjectCodeIsRejectedWith110() {
        CreateSessionReq req = baseRequest();
        CreateSessionReq.SubjectScore item = new CreateSessionReq.SubjectScore();
        item.setSubject("wuli");
        item.setScore(88);
        req.setSubjectScoreList(Lists.newArrayList(item));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.updateScoreDetailForUser(1L, 2L, req, 7L));

        assertEquals(110, error.getStatus());
        assertEquals("非标准选科编码", error.getMessage());
    }

    @Test
    void unknownNumericCodeIsRejectedToo() {
        CreateSessionReq req = baseRequest();
        CreateSessionReq.SubjectScore item = new CreateSessionReq.SubjectScore();
        item.setSubject("09");
        item.setScore(88);
        req.setSubjectScoreList(Lists.newArrayList(item));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.updateScoreDetailForUser(1L, 2L, req, 7L));

        assertEquals(110, error.getStatus(), "09 不是任何科目——静默透传会让上游返回空");
        assertEquals("非标准选科编码", error.getMessage());
    }

    @Test
    void previewPathIsGuardedByTheSameValidation() {
        CreateSessionReq req = baseRequest();
        CreateSessionReq.SubjectScore item = new CreateSessionReq.SubjectScore();
        item.setScore(88);
        req.setSubjectScoreList(Lists.newArrayList(item));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.previewScoreUpdate(1L, 2L, req));

        assertEquals(110, error.getStatus(),
                "预览阶段就要拒：用户还没点确认，不能等确认后才回一句未生效");
        assertEquals("非标准选科编码", error.getMessage());
    }

    @Test
    void emptySubjectListStillFailsWithTheExisting110() {
        CreateSessionReq req = baseRequest();
        req.setSubjectScoreList(Lists.newArrayList());

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.updateScoreDetailForUser(1L, 2L, req, 7L));

        assertEquals(110, error.getStatus());
    }

    @Test
    void missingBatchStillFailsWithTheActionable110() {
        CreateSessionReq req = baseRequest();
        req.setBatch(null);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.updateScoreDetailForUser(1L, 2L, req, 7L));

        assertEquals(110, error.getStatus());
        assertEquals("请选择批次后再创建会话", error.getMessage(),
                "空会话的第二次事故形状：用户看到的那句话要能指导下一步");
    }

    @Test
    void standardCodesPassValidationAndFillMissingHumanNames() {
        CreateSessionReq req = baseRequest();
        CreateSessionReq.SubjectScore physics = new CreateSessionReq.SubjectScore();
        physics.setSubject("01");
        physics.setScore(88);
        CreateSessionReq.SubjectScore chinese = new CreateSessionReq.SubjectScore();
        chinese.setSubject("08");
        chinese.setSubjectName("语文");
        chinese.setScore(112);
        req.setSubjectScoreList(Lists.newArrayList(physics, chinese));

        // 预览里的各科来自**合并后**的成绩（Java 侧算的），正好观测规范化结果。
        ScoreUpdatePreviewDTO preview = service.previewScoreUpdate(1L, 2L, req);

        List<?> subjects = (List<?>) preview.getSummary().get("subjects");
        assertEquals(2, subjects.size());
        Map<?, ?> first = (Map<?, ?>) subjects.get(0);
        assertEquals("01", first.get("subject"));
        assertEquals("物理", first.get("subjectName"), "缺名时按编码补：01 -> 物理");
        Map<?, ?> second = (Map<?, ?>) subjects.get(1);
        assertEquals("语文", second.get("subjectName"), "已有名称不覆盖");
    }

    private CreateSessionReq baseRequest() {
        CreateSessionReq req = new CreateSessionReq();
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setCode("330000");
        province.setName("浙江省");
        req.setProvince(province);
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("WL");
        subjectType.setDesc("物理");
        req.setSubjectType(subjectType);
        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setCode("17");
        batch.setName("第一段");
        batch.setLevel("01");
        batch.setScore(494F);
        req.setBatch(batch);
        req.setTotalScore(610);
        req.setExamYear(2026);
        CreateSessionReq.SubjectScore physics = new CreateSessionReq.SubjectScore();
        physics.setSubject("01");
        physics.setSubjectName("物理");
        physics.setScore(88);
        req.setSubjectScoreList(Lists.newArrayList(physics));
        return req;
    }
}
