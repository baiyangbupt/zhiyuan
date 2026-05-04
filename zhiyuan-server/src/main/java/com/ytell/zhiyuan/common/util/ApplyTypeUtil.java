package com.ytell.zhiyuan.common.util;

/**
 * 申请类型工具类
 * 统一管理申请类型的判断逻辑
 */
public class ApplyTypeUtil {

    /**
     * 专业+院校申请类型常量
     */
    public static final String OTOO = "OTOO";

    /**
     * 专业+院校（文理）申请类型常量
     */
    public static final String OTOOWL = "OTOOWL";

    /**
     * 判断是否为专业+院校类型的申请
     * 包括 OTOO 和 OTOOWL 两种类型
     *
     * @param applyType 申请类型
     * @return 如果是专业+院校类型返回true，否则返回false
     */
    public static boolean isMajorSchoolType(String applyType) {
        return OTOO.equals(applyType) || OTOOWL.equals(applyType);
    }

    /**
     * 判断是否为OTOO类型申请
     *
     * @param applyType 申请类型
     * @return 如果是OTOO类型返回true，否则返回false
     */
    public static boolean isOtooType(String applyType) {
        return OTOO.equals(applyType);
    }

    /**
     * 判断是否为OTOOWL类型申请
     *
     * @param applyType 申请类型
     * @return 如果是OTOOWL类型返回true，否则返回false
     */
    public static boolean isOtoowlType(String applyType) {
        return OTOOWL.equals(applyType);
    }
}
