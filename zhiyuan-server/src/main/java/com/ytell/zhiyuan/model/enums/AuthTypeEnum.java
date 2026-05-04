package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum AuthTypeEnum {
    WECHAT_MP(1, "wechat-mp", "微信小程序"),
    DOUYIN(2, "douyin", "抖音"),
    WECHAT_H5(3, "wechat-h5", "微信H5登录"),
    APP(4, "app", "app"),
    OPPO_AID(5, "oppo_aid", "oppo"),
    KUAISHOU_MP(6, "kuaishou-mp", "kuaishou-mp"),
    WEB(7, "web", "web"),
    BAIDU_MP(8, "baidu-mp", "baidu-mp"),
    HUAWEI_QP(9, "huawei-quickapp", "huawei-quickapp"),
    VIVO_OPENID(10, "vivo-openid", "vivo-openid"),
    OPPO_OPENID(11, "oppo-openid", "oppo-openid"),
    XIAOMI_OPENID(12, "xiaomi-openid", "xiaomi-openid"),
    HUAWEI_OPENID(13, "huawei-openid", "huawei-openid");
    @EnumValue
    private final int code;
    private final String value;
    private final String desc;

}