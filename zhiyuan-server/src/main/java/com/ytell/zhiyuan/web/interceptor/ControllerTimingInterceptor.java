package com.ytell.zhiyuan.web.interceptor;

import com.alibaba.fastjson.JSON;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.ModelAndView;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.util.Map;

/**
 * Controller接口耗时统计拦截器
 * <p>
 * 用于记录所有Controller接口的请求耗时和参数信息
 */
@Slf4j
@Component
public class ControllerTimingInterceptor implements HandlerInterceptor {

    private static final String START_TIME_ATTRIBUTE = "requestStartTime";

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        // 记录请求开始时间
        request.setAttribute(START_TIME_ATTRIBUTE, System.currentTimeMillis());

        // 获取请求参数
        String method = request.getMethod();
        String uri = request.getRequestURI();
        Map<String, String[]> params = request.getParameterMap();

        // 打印请求信息
        log.info("接口请求开始 - URI: {}, 方法: {}, 参数: {}", uri, method, JSON.toJSONString(params));

        return true;
    }

    @Override
    public void postHandle(HttpServletRequest request, HttpServletResponse response, Object handler, ModelAndView modelAndView) {
        // 在这里不做处理，所有的处理放在afterCompletion中
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        // 获取请求开始时间
        Long startTime = (Long) request.getAttribute(START_TIME_ATTRIBUTE);
        if (startTime == null) {
            return;
        }

        // 计算耗时
        long endTime = System.currentTimeMillis();
        long duration = endTime - startTime;

        // 获取请求信息
        String uri = request.getRequestURI();
        String method = request.getMethod();
        int status = response.getStatus();

        // 打印请求耗时信息
        if (ex != null) {
            log.error("接口请求异常 - URI: {}, 方法: {}, 状态码: {}, 耗时: {}ms, 异常: {}",
                    uri, method, status, duration, ex.getMessage());
        } else {
            log.info("接口请求完成 - URI: {}, 方法: {}, 状态码: {}, 耗时: {}ms",
                    uri, method, status, duration);
        }
    }
}