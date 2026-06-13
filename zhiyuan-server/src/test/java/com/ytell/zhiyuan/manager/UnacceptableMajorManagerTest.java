package com.ytell.zhiyuan.manager;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.req.UnAcceptableMajorsReq;
import com.ytell.zhiyuan.model.vo.UnacceptableMajorVO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class UnacceptableMajorManagerTest {

    @Test
    void shouldFallbackWhenNewGaokaoSubjectListMissing() {
        UnacceptableMajorManager manager = new UnacceptableMajorManager();
        manager.init();

        UnAcceptableMajorsReq req = new UnAcceptableMajorsReq();
        req.setEducationLevel("01");
        req.setSubjectType("N");
        req.setSubjectList(null);

        List<UnacceptableMajorVO> result = assertDoesNotThrow(() -> manager.getByReq(req));

        assertFalse(result.isEmpty());
        assertTrue(result.stream().allMatch(item -> "WL".equals(item.getSubjectType())));
    }

    @Test
    void shouldResolveNewGaokaoSubjectTypeFromSelectedSubjects() {
        UnacceptableMajorManager manager = new UnacceptableMajorManager();
        manager.init();

        CreateSessionReq.SubjectItem physics = new CreateSessionReq.SubjectItem();
        physics.setName("物理");
        CreateSessionReq.SubjectItem chemistry = new CreateSessionReq.SubjectItem();
        chemistry.setName("化学");
        UnAcceptableMajorsReq req = new UnAcceptableMajorsReq();
        req.setEducationLevel("01");
        req.setSubjectType("N");
        req.setSubjectList(Arrays.asList(physics, chemistry));

        List<UnacceptableMajorVO> result = manager.getByReq(req);

        assertFalse(result.isEmpty());
        assertTrue(result.stream().allMatch(item -> "WL".equals(item.getSubjectType())));
    }
}
