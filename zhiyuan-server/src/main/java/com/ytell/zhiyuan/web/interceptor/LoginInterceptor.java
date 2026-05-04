package com.ytell.zhiyuan.web.interceptor;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
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

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String token = request.getHeader("tk");
        String platform = request.getHeader("pf");
        //必须有token
        if (Strings.isNullOrEmpty(token) || Strings.isNullOrEmpty(platform)) {
            log.info("login=>token:{},pf:{}", token, platform);
            throw new BusinessException(800, "不合法请求");
        }
        //不同渠道处理不同
        AuthTypeEnum authTypeEnum = AuthTypeEnum.valueOf(platform);
        //微信渠道校验
        if (authTypeEnum.equals(AuthTypeEnum.WECHAT_MP)) {
            UserAuth userAuth = userBizService.getUserAuthByToken(authTypeEnum, token);
            if (userAuth == null) {
                throw new BusinessException(800, "不合法请求");
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
                throw new BusinessException(800, "不合法请求");
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
