package com.ytell.zhiyuan.web.interceptor;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.model.entity.biz.UserAuth;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.service.biz.UserBizService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.handler.HandlerInterceptorAdapter;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

@Service
@Slf4j
public class LoginInterceptor extends HandlerInterceptorAdapter {
    @Autowired
    private UserBizService userBizService;

    /**
     * 未登录的拒绝方式。
     *
     * <p>新路径（对话访问票据）返回**真实的 401**：浏览器与代理要看传输层状态
     * 决定"要不要重新登录"，而 body 里的业务码 800 到不了那一层。
     * 既有路径保持 800 + HTTP 200 不变——那是兼容语义，不能全站改。
     */
    private RuntimeException deny(HttpServletRequest request) {
        String uri = request == null ? "" : String.valueOf(request.getRequestURI());
        if (uri.contains("/conversation/")) {
            return new ConversationAccessException(401, "unauthenticated");
        }
        return new BusinessException(800, "不合法请求");
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String token = request.getHeader("tk");
        String platform = request.getHeader("pf");
        //必须有token
        if (Strings.isNullOrEmpty(token) || Strings.isNullOrEmpty(platform)) {
            log.info("login=>token:{},pf:{}", token, platform);
            throw deny(request);
        }
        //不同渠道处理不同
        AuthTypeEnum authTypeEnum = AuthTypeEnum.valueOf(platform);
        //微信渠道校验
        if (authTypeEnum.equals(AuthTypeEnum.WECHAT_MP)) {
            UserAuth userAuth = userBizService.getUserAuthByToken(authTypeEnum, token);
            if (userAuth == null) {
                throw deny(request);
            }
            //线程缓存数据
            UserBaseData baseData = new UserBaseData();
            baseData.setAuthType(AuthTypeEnum.valueOf(platform));
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
            baseData.setAuthType(AuthTypeEnum.valueOf(platform));
            baseData.setUserId(userCredential.getUserId());
            UserInfoThreadLocalUtil.set(baseData);
        }
        return true;

    }


}
