package com.ytell.zhiyuan.web.controller;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.req.UserInfoAddReq;
import com.ytell.zhiyuan.model.req.UserLoginRequest;
import com.ytell.zhiyuan.model.req.UserMobileLoginRequest;
import com.ytell.zhiyuan.model.req.UserTokenLoginRequest;
import com.ytell.zhiyuan.model.vo.*;
import com.ytell.zhiyuan.service.SmsService;
import com.ytell.zhiyuan.service.biz.UserBizService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/gaotu-assistant-bot/chat/user")
@Slf4j
@Api(tags = "用户登录&信息相关")
public class UserController {
    @Autowired
    private UserBizService userBizService;
    @Autowired
    private SmsService smsService;

    @PostMapping("/login/send-code")
    @ApiOperation("手机号发送验证码")
    public BaseResponse<Boolean> sendVerificationCode(@RequestParam String mobile) {
        smsService.sendVerificationCode(mobile);
        return BaseResponse.success(Boolean.TRUE);
    }

    @PostMapping("/login/by-mobile")
    @ApiOperation("手机号校验验证码")
    public BaseResponse<UserLoginResponse> authByMobile(@RequestBody UserMobileLoginRequest loginRequest) {
        return BaseResponse.success(userBizService.loginOrRegisterByMobile(loginRequest.getMobile(), loginRequest.getVerifyCode()));
    }

    @PostMapping("/login/by-pwd")
    @ApiOperation("用户名密码登录")
    public BaseResponse<UserLoginResponse> login(@RequestBody UserLoginRequest request) {
        return BaseResponse.success(userBizService.login(request));
    }

    @PostMapping("/login/by-token")
    @ApiOperation("渠道token登录")
    public BaseResponse<UserLoginResponse> loginByToken(@RequestBody UserTokenLoginRequest request) {
        return BaseResponse.success(userBizService.loginByToken(request));
    }


    @PostMapping("/login/third-channel")
    @ApiOperation("三方平台（如微信小程序）-用户静默登录")
    public BaseResponse<UserAuthVO> loginByAuth(@RequestParam(name = "authType") AuthTypeEnum authType,
                                                @RequestParam(name = "appId") String appId,
                                                @RequestParam(name = "code") String code) {
        return BaseResponse.success(userBizService.loginOrRegisterByAuth(authType, appId, code));
    }

    @GetMapping("/info")
    @ApiOperation("用户基本信息")
    public BaseResponse<UserVO> getUserInfo() {
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        return BaseResponse.success(userBizService.getUserVoById(userBaseData.getUserId()));
    }


    @PostMapping("/update-info")
    @ApiOperation("更新用户信息：如头像、昵称、分数等")
    public BaseResponse<UserVO> updateUserInfo(@RequestBody UserInfoAddReq req) {
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        userBizService.update(userBaseData.getUserId(), req);
        return BaseResponse.success( userBizService.getUserVoById(userBaseData.getUserId()));
    }


    @PostMapping("/update-phone")
    @ApiOperation("三方平台（如微信小程序）-授权获取手机号")
    public BaseResponse<UserVO> updatePhone(@RequestParam(name = "appId") String appId,
                                            @RequestParam(name = "code") String code) {
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        UserVO userVO;
        try {
            userVO = userBizService.updatePhone(userBaseData.getAuthType(), userBaseData.getUserId(), appId, code);
        } catch (Exception e) {
            log.error("updatePhone:error:", e);
            throw new BusinessException(110, "获取手机号失败");
        }
        return BaseResponse.success(userVO);
    }

    @GetMapping ("/limit-settings")
    @ApiOperation("限制设置")
    public BaseResponse<LimitSituationRes> limitSettings() {
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        LimitSituationRes limitSituationRes = userBizService.limitSituation(userBaseData.getUserId());
        return BaseResponse.success(limitSituationRes);
    }

    @GetMapping ("/check-rights")
    @ApiOperation("权益校验")
    public BaseResponse<CheckRightsResVo> checkRights(@RequestParam("checkPoint") OperateCheckPoint checkPoint) {
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        CheckRightsResVo resVo = userBizService.checkRights(userBaseData.getUserId(),checkPoint);
        return BaseResponse.success(resVo);
    }

}