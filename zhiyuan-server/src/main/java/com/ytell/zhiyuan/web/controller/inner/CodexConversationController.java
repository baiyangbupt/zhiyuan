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
import org.springframework.web.bind.annotation.GetMapping;
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

    /**
     * 该 (租户, 会话) 当前有效的绑定；没有绑定时 data 为 null。
     *
     * <p>Gateway 重启后进程内的 thread 表就没了，靠这条把 thread 找回来，
     * 否则用户会得到一个"记得你的资料、不记得你刚说过什么"的对话。
     * 只对认证过的内部调用方开放。</p>
     */
    @GetMapping("/thread-binding/current")
    public BaseResponse<CodexThreadBindingContextRes> current(
            @PathVariable("tenantId") Long tenantId,
            @RequestParam("chatSessionId") Long chatSessionId) {
        return BaseResponse.success(bindingService.current(tenantId, chatSessionId));
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
