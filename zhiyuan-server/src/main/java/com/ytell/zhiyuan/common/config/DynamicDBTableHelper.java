package com.ytell.zhiyuan.common.config;

public class DynamicDBTableHelper {
    /**
     * 请求参数存取
     */
    private static final ThreadLocal<String> REQUEST_DATA = new ThreadLocal<>();

    /**
     * 获取请求参数
     */
    public static String getSuffix() {
        return REQUEST_DATA.get();
    }

    /**
     * 设置请求参数
     *
     * @param
     */
    public static void setSuffix(String suffix) {
        REQUEST_DATA.set(suffix);
    }

    /**
     * 删除请求参数
     */
    public static void removeSuffix() {
        REQUEST_DATA.remove();
    }
}
