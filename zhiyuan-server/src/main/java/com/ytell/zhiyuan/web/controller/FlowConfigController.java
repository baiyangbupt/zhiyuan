package com.ytell.zhiyuan.web.controller;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.service.FlowConfigService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import io.swagger.annotations.Api;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 高考志愿-模拟数字人填报流程配置
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/chat/{tenantId}/collect-flow")
@Slf4j
@Api(tags = "高考志愿-模拟数字人填报流程配置")
public class FlowConfigController {

    @Autowired
    private  FlowConfigService flowConfigService;

    /**
     * 获取完整的流程配置
     * @return 总是返回填充了用户数据和选项数据的完整配置
     */
    @GetMapping
    public BaseResponse<JSONObject> getFlowConfig() {
        try {
            // 获取当前登录用户信息
            UserBaseData userBaseData = UserInfoThreadLocalUtil.get();

            JSONObject flowConfig = flowConfigService.getFlowConfigWithUserData(userBaseData.getUserId());

            if (flowConfig == null) {
                return BaseResponse.error(404, "获取流程配置失败：配置模板为空");
            }
            return BaseResponse.success(flowConfig);
        } catch (Exception e) {
            log.error("Failed to get flow config", e);
            return BaseResponse.error(404, "获取流程配置失败: " + e.getMessage());
        }
    }
}
