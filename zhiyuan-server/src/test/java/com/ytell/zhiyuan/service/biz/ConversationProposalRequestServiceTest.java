package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.entity.biz.ConversationProposalRequestEntity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.dao.DuplicateKeyException;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;

/**
 * prepare 幂等状态机的证据。
 *
 * <p>用一张**内存假表**（同一个 key 唯一、插入冲突抛 DuplicateKeyException）来跑真实的
 * 服务逻辑，而不是把服务方法逐个 mock 掉——被 mock 掉的正是"状态怎么走"这件事本身。
 * 真表上才能验的部分（唯一键真的生效、重启后真的还在）在门控集成测试里。
 */
public class ConversationProposalRequestServiceTest {

    private ConversationProposalRequestService service;
    private final Map<String, ConversationProposalRequestEntity> table = new LinkedHashMap<>();
    private final AtomicInteger idSeq = new AtomicInteger();

    @BeforeEach
    void setUp() {
        table.clear();
        idSeq.set(0);
        // 匿名子类 = 假表；只替换存储层，状态机逻辑仍走真实实现。
        service = new ConversationProposalRequestService() {
            @Override
            public ConversationProposalRequestEntity find(Long tenantId, Long chatSessionId, String requestId) {
                return table.get(key(tenantId, chatSessionId, requestId));
            }

            @Override
            protected int supersedeSiblings(Long tenantId, Long chatSessionId, String requestId) {
                int affected = 0;
                for (ConversationProposalRequestEntity row : table.values()) {
                    boolean sameScope = row.getTenantId().equals(tenantId)
                            && row.getChatSessionId().equals(chatSessionId);
                    if (sameScope
                            && !row.getRequestId().equals(requestId)
                            && ConversationProposalRequestService.STATUS_PREPARED.equals(row.getStatus())) {
                        row.setStatus(ConversationProposalRequestService.STATUS_SUPERSEDED);
                        affected++;
                    }
                }
                return affected;
            }
        };
        com.ytell.zhiyuan.mapper.ConversationProposalRequestMapper mapper =
                Mockito.mock(com.ytell.zhiyuan.mapper.ConversationProposalRequestMapper.class);
        Mockito.when(mapper.insert(any(ConversationProposalRequestEntity.class))).thenAnswer(invocation -> {
            ConversationProposalRequestEntity row = invocation.getArgument(0);
            String key = key(row.getTenantId(), row.getChatSessionId(), row.getRequestId());
            if (table.containsKey(key)) {
                throw new DuplicateKeyException("uk_conversation_proposal_request");
            }
            row.setId((long) idSeq.incrementAndGet());
            table.put(key, row);
            return 1;
        });
        Mockito.when(mapper.updateById(any(ConversationProposalRequestEntity.class))).thenAnswer(invocation -> {
            ConversationProposalRequestEntity row = invocation.getArgument(0);
            table.put(key(row.getTenantId(), row.getChatSessionId(), row.getRequestId()), row);
            return 1;
        });
        // 显式类型见证：deleteById 有多个重载，any() 会让编译器无法选择。
        Mockito.when(mapper.deleteById(Mockito.<java.io.Serializable>any())).thenAnswer(invocation -> {
            table.values().removeIf(row -> row.getId().equals(((Number) invocation.getArgument(0)).longValue()));
            return 1;
        });
        org.springframework.test.util.ReflectionTestUtils.setField(service, "requestMapper", mapper);
    }

    @Test
    void retryingTheSameRequestIdDoesNotPrepareTwice() {
        AtomicInteger runs = new AtomicInteger();

        PrepareResultDTO first = service.prepareOnce(1L, 2L, "req-1", "digest-1", null,
                () -> outcome(runs, "pending-1", "op-1"));

        PrepareResultDTO retry = service.prepareOnce(1L, 2L, "req-1", "digest-1", null,
                () -> outcome(runs, "pending-2", "op-2"));

        assertEquals(1, runs.get(), "同 requestId 同摘要不该再编译一次");
        assertEquals("prepared", first.getStatus());
        assertEquals("prepared", retry.getStatus());
        // 重发拿到的是**原来那次**的结果，不是一个新建的预览。
        assertEquals("op-1", retry.getOperationId());
        assertEquals("pending-1", retry.getPendingId());
    }

    @Test
    void sameRequestIdWithDifferentContentIsAConflict() {
        service.prepareOnce(1L, 2L, "req-1", "digest-1", null, () -> outcome(new AtomicInteger(), "p", "o"));

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareOnce(1L, 2L, "req-1", "digest-2", null,
                        () -> outcome(new AtomicInteger(), "p2", "o2")));

        // 挑一个执行是错的：挑中的那个可能不是用户确认过的那个。
        assertEquals(409, ex.getStatus());
        assertEquals("prepare_request_conflict", ex.getMessage());
    }

    @Test
    void prepareBThenRetryASeversAInsteadOfReRunningIt() {
        AtomicInteger runsA = new AtomicInteger();
        AtomicInteger runsB = new AtomicInteger();

        service.prepareOnce(1L, 2L, "req-A", "digest-A", null, () -> outcome(runsA, "pending-A", "op-A"));
        service.prepareOnce(1L, 2L, "req-B", "digest-B", null, () -> outcome(runsB, "pending-B", "op-B"));

        PrepareResultDTO retryA = service.prepareOnce(1L, 2L, "req-A", "digest-A", null, () -> {
            throw new AssertionError("已被取代的 requestId 不该重新执行 prepareWork");
        });

        assertEquals(1, runsA.get());
        assertEquals(1, runsB.get());
        assertEquals("superseded", retryA.getStatus());
        assertEquals("pending-A", retryA.getPendingId(), "superseded 仍要能指回被打回的那份");
    }

    @Test
    void prepareIsRejectedWhileAPendingIsApplying() {
        AtomicInteger runs = new AtomicInteger();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareOnce(1L, 2L, "req-new", "digest-new",
                        ConversationProposalRequestService.STATUS_APPLYING,
                        () -> outcome(runs, "pending-new", "op-new")));

        // 事务正在跑，换一份 Proposal 会让"用户确认过的"和"正在执行的"对不上。
        assertEquals(409, ex.getStatus());
        assertEquals("pending_applying", ex.getMessage());
        assertEquals(0, runs.get());
        assertTrue(table.isEmpty(), "被拒绝的 prepare 不该留下记录");
    }

    @Test
    void aFailedPrepareLeavesNoOccupyingRow() {
        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareOnce(1L, 2L, "req-fail", "digest-fail", null, () -> {
                    throw new BusinessException(500, "preview_exploded");
                }));

        assertEquals(500, ex.getStatus());
        // 占位必须清掉：留着 preparing 会让重试永远拿到"正在生成中"而其实什么都没产出。
        assertTrue(table.isEmpty());

        AtomicInteger runs = new AtomicInteger();
        PrepareResultDTO retry = service.prepareOnce(1L, 2L, "req-fail", "digest-fail", null,
                () -> outcome(runs, "pending-ok", "op-ok"));
        assertEquals("prepared", retry.getStatus());
        assertEquals(1, runs.get());
    }

    @Test
    void aDifferentRequestIdIsAcceptedAndSupersedesThePreviousOne() {
        service.prepareOnce(1L, 2L, "req-A", "digest-A", null, () -> outcome(new AtomicInteger(), "pending-A", "op-A"));

        PrepareResultDTO b = service.prepareOnce(1L, 2L, "req-B", "digest-B", null,
                () -> outcome(new AtomicInteger(), "pending-B", "op-B"));

        assertEquals("prepared", b.getStatus());
        assertEquals(ConversationProposalRequestService.STATUS_SUPERSEDED,
                table.get(key(1L, 2L, "req-A")).getStatus());
    }

    @Test
    void anotherSessionsRequestIsNotAffectedBySupersede() {
        service.prepareOnce(1L, 2L, "req-A", "digest-A", null, () -> outcome(new AtomicInteger(), "p-A", "o-A"));
        service.prepareOnce(1L, 3L, "req-C", "digest-C", null, () -> outcome(new AtomicInteger(), "p-C", "o-C"));

        service.prepareOnce(1L, 2L, "req-B", "digest-B", null, () -> outcome(new AtomicInteger(), "p-B", "o-B"));

        // 取代只发生在会话内部：另一个会话的预览不该被顺手作废。
        assertEquals(ConversationProposalRequestService.STATUS_PREPARED,
                table.get(key(1L, 3L, "req-C")).getStatus());
    }

    @Test
    void missingRequestIdOrDigestIsRefused() {
        AtomicInteger runs = new AtomicInteger();

        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.prepareOnce(1L, 2L, "  ", "digest", null, () -> outcome(runs, "p", "o"))).getStatus());
        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.prepareOnce(1L, 2L, "req", "", null, () -> outcome(runs, "p", "o"))).getStatus());
        assertEquals(0, runs.get());
    }

    private static ConversationProposalRequestService.PrepareOutcome outcome(
            AtomicInteger runs, String pendingId, String operationId) {
        runs.incrementAndGet();
        return new ConversationProposalRequestService.PrepareOutcome(pendingId, operationId, "{\"ok\":true}");
    }

    private static String key(Long tenantId, Long chatSessionId, String requestId) {
        return tenantId + ":" + chatSessionId + ":" + requestId;
    }
}
