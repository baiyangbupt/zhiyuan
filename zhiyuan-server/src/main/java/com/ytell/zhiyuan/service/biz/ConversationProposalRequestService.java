package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.ConversationProposalRequestMapper;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.entity.biz.ConversationProposalRequestEntity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.util.Date;

/**
 * prepare 的幂等与取代语义。
 *
 * <p>为什么不能靠 Pending 表：Pending 是每会话一行的**状态**，每次 prepare 都会把它
 * 覆盖掉。于是"重试同一个 requestId"在 Pending 上看起来和"新的一次 prepare"一模一样，
 * 两者都会重新编译一遍预览、生成一个新的 operationId——而用户只是没收到回包而已。
 *
 * <p>状态机（记录不可覆盖，只在前进一步时改写 status）：
 * <pre>
 *   preparing --完成--> prepared --被后一次取代--> superseded
 * </pre>
 * {@code superseded} 是终态：**不复活**。重试一个已被取代的 requestId 必须拿到
 * "已被取代"，而不是把它重新执行一遍——用户看到的旧卡已经失效了。
 */
@Service
public class ConversationProposalRequestService {

    private static final Logger log = LoggerFactory.getLogger(ConversationProposalRequestService.class);

    public static final String STATUS_PREPARING = "preparing";
    public static final String STATUS_PREPARED = "prepared";
    public static final String STATUS_SUPERSEDED = "superseded";
    public static final String STATUS_APPLYING = "applying";

    @Autowired
    private ConversationProposalRequestMapper requestMapper;

    /** prepare 的实际工作。由调用方提供，本服务只管幂等与状态。 */
    public interface PrepareWork {
        PrepareOutcome run();
    }

    public static class PrepareOutcome {
        private final String pendingId;
        private final String operationId;
        private final Object result;

        public PrepareOutcome(String pendingId, String operationId, Object result) {
            this.pendingId = pendingId;
            this.operationId = operationId;
            this.result = result;
        }

        public String getPendingId() {
            return pendingId;
        }

        public String getOperationId() {
            return operationId;
        }

        public Object getResult() {
            return result;
        }
    }

    /**
     * @param activePendingStatus 当前会话的 Pending 状态（可为 null）。
     *                            {@code applying} 时拒绝新 prepare：事务正在跑，
     *                            换一份 Proposal 会让"用户确认过的"和"正在执行的"对不上。
     */
    public PrepareResultDTO prepareOnce(Long tenantId, Long chatSessionId, String requestId,
                                        String requestDigest, String activePendingStatus,
                                        PrepareWork work) {
        requireArgs(tenantId, chatSessionId, requestId, requestDigest);

        ConversationProposalRequestEntity existing = find(tenantId, chatSessionId, requestId);
        if (existing != null) {
            return replay(existing, requestDigest);
        }
        if (STATUS_APPLYING.equals(activePendingStatus)) {
            throw new BusinessException(409, "pending_applying");
        }

        ConversationProposalRequestEntity placeholder = new ConversationProposalRequestEntity();
        placeholder.setTenantId(tenantId);
        placeholder.setChatSessionId(chatSessionId);
        placeholder.setRequestId(requestId);
        placeholder.setRequestDigest(requestDigest);
        placeholder.setStatus(STATUS_PREPARING);
        placeholder.setCreateTime(new Date());
        placeholder.setUpdateTime(new Date());
        try {
            // 先占位再干活：唯一键是并发防线。两个并发请求里只有一个能插进去，
            // 另一个会拿到 DuplicateKeyException 并走"重放已有记录"的分支——
            // 反过来先干活再插入的话，两边都会跑一遍 prepareWork。
            requestMapper.insert(placeholder);
        } catch (DuplicateKeyException duplicate) {
            ConversationProposalRequestEntity raced = find(tenantId, chatSessionId, requestId);
            if (raced == null) {
                throw duplicate;
            }
            return replay(raced, requestDigest);
        }

        PrepareOutcome outcome;
        try {
            outcome = work.run();
        } catch (RuntimeException failure) {
            // 干活失败就把占位清掉：留着 preparing 会让重试永远拿不到"可以重做"，
            // 而它其实什么都没产出。
            requestMapper.deleteById(placeholder.getId());
            throw failure;
        }

        placeholder.setPendingId(outcome.getPendingId());
        placeholder.setOperationId(outcome.getOperationId());
        placeholder.setResultJson(outcome.getResult() == null ? null : JSON.toJSONString(outcome.getResult()));
        placeholder.setStatus(STATUS_PREPARED);
        placeholder.setUpdateTime(new Date());
        requestMapper.updateById(placeholder);

        supersedeSiblings(tenantId, chatSessionId, requestId);

        PrepareResultDTO dto = new PrepareResultDTO();
        dto.setStatus(STATUS_PREPARED);
        dto.setRequestId(requestId);
        dto.setPendingId(outcome.getPendingId());
        dto.setOperationId(outcome.getOperationId());
        dto.setResult(outcome.getResult());
        return dto;
    }

    private PrepareResultDTO replay(ConversationProposalRequestEntity existing, String requestDigest) {
        if (!requestDigest.equals(existing.getRequestDigest())) {
            // 同一个 requestId 两个不同内容：调用方把两次 prepare 搞混了。
            // 挑一个执行是错的——挑中的那个可能不是用户确认过的那个。
            throw new BusinessException(409, "prepare_request_conflict");
        }
        PrepareResultDTO dto = new PrepareResultDTO();
        dto.setRequestId(existing.getRequestId());
        dto.setPendingId(existing.getPendingId());
        dto.setOperationId(existing.getOperationId());
        if (STATUS_SUPERSEDED.equals(existing.getStatus())) {
            dto.setStatus(STATUS_SUPERSEDED);
            dto.setMessage("该预览已被后一次取代，请使用最新预览");
            return dto;
        }
        if (STATUS_PREPARING.equals(existing.getStatus())) {
            // 占位还在：另一个请求正在做同一件事，让调用方稍后按 operationId 查。
            dto.setStatus(STATUS_PREPARING);
            dto.setMessage("该预览正在生成中，请稍后查询结果");
            return dto;
        }
        dto.setStatus(existing.getStatus());
        dto.setResult(existing.getResultJson() == null ? null : JSON.parse(existing.getResultJson()));
        return dto;
    }

    /** 新 B 生效时把同会话其它 prepared 记录标 superseded——旧卡不能还能点。 */
    protected int supersedeSiblings(Long tenantId, Long chatSessionId, String requestId) {
        UpdateWrapper<ConversationProposalRequestEntity> update = new UpdateWrapper<>();
        update.eq("tenant_id", tenantId);
        update.eq("chat_session_id", chatSessionId);
        update.ne("request_id", requestId);
        update.eq("status", STATUS_PREPARED);
        update.set("status", STATUS_SUPERSEDED);
        update.set("update_time", new Date());
        int affected = requestMapper.update(null, update);
        if (affected > 0) {
            log.info("superseded {} prior proposal request(s) for session {}", affected, chatSessionId);
        }
        return affected;
    }

    public ConversationProposalRequestEntity find(Long tenantId, Long chatSessionId, String requestId) {
        QueryWrapper<ConversationProposalRequestEntity> query = new QueryWrapper<>();
        query.eq("tenant_id", tenantId);
        query.eq("chat_session_id", chatSessionId);
        query.eq("request_id", requestId);
        return requestMapper.selectOne(query);
    }

    private void requireArgs(Long tenantId, Long chatSessionId, String requestId, String requestDigest) {
        if (tenantId == null || chatSessionId == null) {
            throw new BusinessException(400, "prepare_scope_required");
        }
        if (requestId == null || requestId.trim().isEmpty()) {
            // 没有 requestId 就没有幂等：重发会被当成新请求再执行一次。
            throw new BusinessException(400, "prepare_request_id_required");
        }
        if (requestDigest == null || requestDigest.trim().isEmpty()) {
            throw new BusinessException(400, "prepare_request_digest_required");
        }
    }
}
