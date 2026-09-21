package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.planning.ArtifactDTO;
import com.ytell.zhiyuan.model.dto.planning.ArtifactPageDTO;
import com.ytell.zhiyuan.service.biz.ConversationArtifactService;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 产物读取。**只给内部调用**（前缀 {@code /gaotu-assistant-bot/inner/}）。
 *
 * <p>公开 facade 只映射允许展示的字段，不复用这个端点——
 * 产物里可能含冻结命令与个人资料全文，那些不出去。
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/inner/planning/{tenantId}/session")
@Api(tags = "会话产物接口")
public class ConversationArtifactController {

    @Autowired
    private ConversationArtifactService artifactService;

    @GetMapping("/artifacts/{artifactId}")
    public BaseResponse<ArtifactDTO> get(
            @PathVariable("tenantId") Long tenantId,
            @RequestParam("chatSessionId") Long chatSessionId,
            @PathVariable("artifactId") String artifactId) {
        return BaseResponse.success(artifactService.getOwned(tenantId, chatSessionId, artifactId));
    }

    @GetMapping("/artifacts/{artifactId}/page")
    public BaseResponse<ArtifactPageDTO> page(
            @PathVariable("tenantId") Long tenantId,
            @RequestParam("chatSessionId") Long chatSessionId,
            @PathVariable("artifactId") String artifactId,
            @RequestParam(value = "cursor", required = false) String cursor,
            @RequestParam(value = "limit", required = false) Integer limit) {
        return BaseResponse.success(
                artifactService.pageOwned(tenantId, chatSessionId, artifactId, cursor, limit));
    }
}
