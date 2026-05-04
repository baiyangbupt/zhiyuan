package com.ytell.zhiyuan.common.util;

import java.math.BigDecimal;

public class DataDealUtil {

    /**
     * 隐藏手机号中间四位
     *
     * @param phone 原始手机号
     * @return 隐藏中间四位后的手机号
     */
    public static String hideMiddleFourDigits(String phone) {
        if (phone == null || phone.length() != 11) {
            // 如果手机号格式不正确，直接返回原值
            return phone;
        }
        // 取手机号的前三位和后四位，并在中间插入四个星号
        return phone.substring(0, 3) + "****" + phone.substring(7);
    }

    public static String div(int a, int b) {

        BigDecimal ba = new BigDecimal(a);
        BigDecimal bb = new BigDecimal(b);
        BigDecimal result = ba.divide(bb, 2, BigDecimal.ROUND_HALF_UP);
        return result.toString();
    }

    public static String formatActionNumber(Long number) {
        if (number == null) {
            return "0";
        }

        if (number < 10000) {
            return number.toString();
        } else {
            double value = number / 10000.0;
            // 保留一位小数，并去除末尾的 .0（如 1.0 万 -> 1 万）
            String formatted = String.format("%.1f", value);
            if (formatted.endsWith(".0")) {
                formatted = formatted.substring(0, formatted.length() - 2);
            }
            return formatted + "万";
        }
    }

    public static String formatDuration(Integer duration) {
        if (duration > 60) {
            Integer minutes = duration / 60;
            Integer seconds = duration % 60;
            return minutes + "分" + seconds + "秒";

        } else {
            return duration + "秒";
        }
    }
}
