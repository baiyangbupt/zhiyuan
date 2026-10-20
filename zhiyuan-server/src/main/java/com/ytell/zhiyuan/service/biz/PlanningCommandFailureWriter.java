package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.Objects;

@Service
public class PlanningCommandFailureWriter {
    @Autowired
    private PlanningPendingCommandSharedService commandSharedService;
    @Autowired
    private PendingConfirmationSharedService pendingSharedService;

    @Transactional(propagation = Propagation.REQUIRES_NEW, rollbackFor = Exception.class)
    public void recordFailure(PlanningPendingCommandEntity command, PendingConfirmationEntity owner,
                              RuntimeException failure) {
        PendingConfirmationEntity current = pendingSharedService.lockCurrent(
                command.getTenantId(), command.getChatSessionId());
        if (commandSharedService.getByOperationId(command.getOperationId()) != null) {
            return;
        }
        int errorCode = failure instanceof BusinessException ? ((BusinessException) failure).getStatus() : 500;
        JSONObject receipt = new JSONObject(true);
        receipt.put("status", "failed");
        receipt.put("errorCode", errorCode);
        receipt.put("reasonCode", failureReason(failure));
        PlanningPendingCommandEntity failed = new PlanningPendingCommandEntity();
        failed.setTenantId(command.getTenantId());
        failed.setChatSessionId(command.getChatSessionId());
        failed.setPendingId(command.getPendingId());
        failed.setOperationId(command.getOperationId());
        failed.setCommandType(command.getCommandType());
        failed.setExpectedPlanVersion(command.getExpectedPlanVersion());
        failed.setRequestDigest(command.getRequestDigest());
        failed.setStatus("failed");
        failed.setResultJson(receipt.toJSONString());
        if (!commandSharedService.save(failed)) {
            throw new IllegalStateException("planning failure audit was not saved");
        }
        if (current == null || current.getRevision() == null || !"applying".equals(current.getStatus())
                || !Objects.equals(owner.getPendingId(), current.getPendingId())
                || !Objects.equals(owner.getRevision(), current.getRevision())
                || !Objects.equals(owner.getClaimToken(), current.getClaimToken())) {
            return;
        }
        JSONObject data;
        try {
            data = JSONObject.parseObject(current.getDataValue());
        } catch (RuntimeException invalidPayload) {
            return;
        }
        if (data == null || !command.getOperationId().equals(data.getString("operationId"))) {
            return;
        }
        PendingConfirmationEntity next = JSONObject.parseObject(
                JSONObject.toJSONString(current), PendingConfirmationEntity.class);
        next.setRevision(current.getRevision() + 1L);
        next.setStatus("expired");
        next.setClaimExpiresAt(null);
        next.setResultCode(String.valueOf(errorCode));
        next.setResolvedAction("fail");
        data.put("status", "expired");
        data.put("revision", next.getRevision());
        next.setDataValue(data.toJSONString());
        pendingSharedService.compareAndSet(next, current.getRevision(), current.getPendingId(), "applying");
    }

    private String failureReason(RuntimeException failure) {
        String message = failure.getMessage();
        if (message != null) {
            String reason = message.split("[:\\s]", 2)[0];
            if (reason.matches("review_fix_[a-z_]{1,64}")) {
                return reason;
            }
        }
        if (failure instanceof BusinessException) {
            return ((BusinessException) failure).getStatus() == PendingPlanningCommandBizService.PLAN_VERSION_CONFLICT_CODE
                    ? "planning_version_conflict" : "planning_command_rejected";
        }
        return "planning_command_error";
    }
}
