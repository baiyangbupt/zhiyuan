package com.ytell.zhiyuan.web.interceptor;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.model.entity.biz.UserAuth;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.service.biz.UserBizService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.handler.HandlerInterceptorAdapter;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

@Service
public class LoginInterceptor extends HandlerInterceptorAdapter {
    @Autowired
    private UserBizService userBizService;

    /**
     * 工作台公开 facade 路径：`/gaotu-assistant-bot/chat/{tenantId}/planning/...`。
     *
     * <p>刻意不写成 `contains("/planning/")`：那样会连别的路径一起改掉状态码语义。
     * 允许前缀（如 context path）存在，`.matches()` 要求整串命中，不多吃一段。</p>
     */
    private static final java.util.regex.Pattern PLANNING_FACADE_URI =
            java.util.regex.Pattern.compile("^.*/chat/[^/]+/planning(?:/.*)?$");

    /**
     * 未登录的拒绝方式。
     *
     * <p>新路径（对话访问票据、工作台 facade）返回**真实的 401**：浏览器与代理要看
     * 传输层状态决定"要不要重新登录"，而 body 里的业务码 800 到不了那一层。
     * 既有路径保持 800 + HTTP 200 不变——那是兼容语义，不能全站改。
     */
    private RuntimeException deny(HttpServletRequest request) {
        String uri = request == null ? "" : String.valueOf(request.getRequestURI());
        if (uri.contains("/conversation/") || PLANNING_FACADE_URI.matcher(uri).matches()) {
            return new ConversationAccessException(401, "unauthenticated");
        }
        return new BusinessException(800, "不合法请求");
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        // Servlet worker threads are reused, including after rejected requests.
        UserInfoThreadLocalUtil.remove();
        String token = request.getHeader("tk");
        String platform = request.getHeader("pf");
        //必须有token
        if (Strings.isNullOrEmpty(token) || Strings.isNullOrEmpty(platform)) {
            throw deny(request);
        }
        //不同渠道处理不同
        AuthTypeEnum authTypeEnum;
        try {
            authTypeEnum = AuthTypeEnum.valueOf(platform);
        } catch (IllegalArgumentException exception) {
            throw deny(request);
        }
        //微信渠道校验
        if (authTypeEnum.equals(AuthTypeEnum.WECHAT_MP)) {
            UserAuth userAuth = userBizService.getUserAuthByToken(authTypeEnum, token);
            if (userAuth == null) {
                throw deny(request);
            }
            //线程缓存数据
            UserBaseData baseData = new UserBaseData();
            baseData.setAuthType(authTypeEnum);
            baseData.setUnionId(userAuth.getUnionId());
            baseData.setOpenId(userAuth.getOpenId());
            baseData.setUserId(userAuth.getUserId());
            UserInfoThreadLocalUtil.set(baseData);
        } else {
            //
            UserCredential userCredential = userBizService.getUserCredentialByToken(token);
            if (userCredential == null) {
                throw deny(request);
            }
            //线程缓存数据
            UserBaseData baseData = new UserBaseData();
            baseData.setAuthType(authTypeEnum);
            baseData.setUserId(userCredential.getUserId());
            UserInfoThreadLocalUtil.set(baseData);
        }
        return true;

    }

    @Override
    public void afterConcurrentHandlingStarted(HttpServletRequest request, HttpServletResponse response,
                                               Object handler) {
        // Async MVC releases this worker before afterCompletion on redispatch.
        UserInfoThreadLocalUtil.remove();
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
                                Object handler, Exception exception) {
        UserInfoThreadLocalUtil.remove();
    }
}
