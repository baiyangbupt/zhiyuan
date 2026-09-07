package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingReq;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingContextRes;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingResolveReq;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingRes;
import com.ytell.zhiyuan.service.biz.CodexThreadBindingService;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/codex/{tenantId}")
@Api(tags = "Codex 对话绑定接口")
public class CodexConversationController {

    @Autowired
    private CodexThreadBindingService bindingService;

    @PostMapping("/thread-binding")
    public BaseResponse<CodexThreadBindingRes> register(
            @PathVariable("tenantId") Long tenantId,
            @RequestBody CodexThreadBindingReq req) {
        return BaseResponse.success(bindingService.registerResponse(tenantId, req));
    }

    @PostMapping("/thread-binding/resolve")
    public BaseResponse<CodexThreadBindingContextRes> resolve(
            @PathVariable("tenantId") Long tenantId,
            @RequestBody CodexThreadBindingResolveReq req) {
        return BaseResponse.success(bindingService.resolveResponse(tenantId, req));
    }

    @DeleteMapping("/thread-binding")
    public BaseResponse<Boolean> revoke(
            @PathVariable("tenantId") Long tenantId,
            @RequestParam("threadId") String threadId) {
        bindingService.revoke(tenantId, threadId);
        return BaseResponse.success(true);
    }
}
