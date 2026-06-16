package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.common.base.BaseResponse;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/ops")
@Api(tags = "内部使用接口")
public class OpsHealthController {

    @Value("${spring.profiles.active:unknown}")
    private String activeProfile;

    @Value("${spring.application.name:zhiyuan-server}")
    private String applicationName;

    @GetMapping("/health")
    @ApiOperation("内部健康检查")
    public BaseResponse<Map<String, Object>> health() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("status", "UP");
        data.put("application", applicationName);
        data.put("profile", activeProfile);
        return BaseResponse.success(data);
    }
}
