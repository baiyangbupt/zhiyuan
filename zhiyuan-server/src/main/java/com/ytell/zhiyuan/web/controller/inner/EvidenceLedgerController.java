package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyReq;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyRes;
import com.ytell.zhiyuan.service.biz.EvidenceLedgerService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Slf4j
@RestController
@RequestMapping("/internal/evidence")
@Api(tags = "内部使用接口")
public class EvidenceLedgerController {

    @Autowired
    private EvidenceLedgerService evidenceLedgerService;

    /**
     * 批量核验证据。一个回合一次调用，返回 valid|stale|expired|unknown 四态。
     *
     * <p>Java 不可达时调用方必须硬失败，不得降级放行——验证不了就不能盖权威章。</p>
     */
    @PostMapping("/verify")
    @ApiOperation("批量核验证据状态")
    public BaseResponse<EvidenceVerifyRes> verify(@RequestBody EvidenceVerifyReq req) {
        log.info("verifyEvidence: tenantId={}, chatSessionId={}, threadId={}, evidenceIds={}",
                req == null ? null : req.getTenantId(),
                req == null ? null : req.getChatSessionId(),
                req == null ? null : req.getThreadId(),
                req == null ? null : req.getEvidenceIds());
        return BaseResponse.success(evidenceLedgerService.verify(req));
    }
}
