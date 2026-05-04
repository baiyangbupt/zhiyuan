package com.ytell.zhiyuan.service;

import cn.binarywang.wx.miniapp.api.WxMaService;
import cn.binarywang.wx.miniapp.bean.WxMaJscode2SessionResult;
import cn.binarywang.wx.miniapp.bean.WxMaPhoneNumberInfo;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.cache.ThirdChannelSessionKeyCache;
import com.ytell.zhiyuan.model.dto.ThirdChannelLoginDto;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
@Slf4j
public class ThirdChannelLoginService {

    @Autowired
    private WxMaService wxMaService;
    @Autowired
    private ThirdChannelSessionKeyCache thirdChannelSessionKeyCache;

    public ThirdChannelLoginDto login(AuthTypeEnum authType, String appId, String code) {
        ThirdChannelLoginDto loginDto = new ThirdChannelLoginDto();
        loginDto.setAuthType(authType);

        try {
            if (AuthTypeEnum.WECHAT_MP.equals(authType)) {
                // 微信登录
                if (StringUtils.isBlank(code)) {
                    throw new BusinessException(-1, "wx code is empty");
                }

                if (!wxMaService.switchover(appId)) {
                    throw new BusinessException(-1, String.format("微信未找到对应appid=[%s]的配置，请核实！", appId));
                }
                WxMaJscode2SessionResult sessionInfo = wxMaService.getUserService().getSessionInfo(code);
                loginDto.setOpenId(sessionInfo.getOpenid());
                loginDto.setUnionId(Strings.isNullOrEmpty(sessionInfo.getUnionid()) ? sessionInfo.getOpenid() : sessionInfo.getUnionid());
                loginDto.setSessionKey(sessionInfo.getSessionKey());
            }

            //缓存sessionKey,用于一些接口的解密
            try {
                if (loginDto.getSessionKey() != null) {
                    thirdChannelSessionKeyCache.saveOrUpdate(authType, loginDto.getOpenId(), loginDto.getSessionKey());
                }
            } catch (Exception e) {
                log.error("thirdChannelSessionKeyCache:error", e);
            }
            return loginDto;
        } catch (Exception e) {
            log.error("Third channel login failed", e);
            throw new RuntimeException("Login failed: " + e.getMessage());
        }
    }

    public String getPhoneNumber(AuthTypeEnum authType, String appId, String code) throws Exception {

        if (AuthTypeEnum.WECHAT_MP.equals(authType)) {
            // 微信登录
            if (StringUtils.isBlank(code)) {
                throw new BusinessException(-1, "wx code is empty");
            }
            if (!wxMaService.switchover(appId)) {
                throw new BusinessException(-1, String.format("微信未找到对应appid=[%s]的配置，请核实！", appId));
            }
            WxMaPhoneNumberInfo wxMaPhoneNumberInfo = wxMaService.getUserService().getPhoneNoInfo(code);
            return wxMaPhoneNumberInfo.getPurePhoneNumber();
        }
        return null;
    }
}
