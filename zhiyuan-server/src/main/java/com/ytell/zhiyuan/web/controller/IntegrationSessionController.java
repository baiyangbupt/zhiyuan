package com.ytell.zhiyuan.web.controller;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeReq;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeRes;
import com.ytell.zhiyuan.service.biz.IntegrationSessionService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/gaotu-assistant-bot/chat/{tenantId}/integration")
@Slf4j
@Api(tags = "外部集成接口")
public class IntegrationSessionController {

    @Autowired
    private IntegrationSessionService integrationSessionService;

    @PostMapping("/session/initialize")
    @ApiOperation("外部授权初始化会话并生成方案")
    public BaseResponse<ExternalSessionInitializeRes> initializeSession(@PathVariable("tenantId") Long tenantId,
                                                                        @RequestBody ExternalSessionInitializeReq req) {
        log.info("initializeExternalSession: tenantId={}, req={}", tenantId, JSONObject.toJSONString(req));
        return BaseResponse.success(integrationSessionService.initializeSession(tenantId, req));
    }
}
