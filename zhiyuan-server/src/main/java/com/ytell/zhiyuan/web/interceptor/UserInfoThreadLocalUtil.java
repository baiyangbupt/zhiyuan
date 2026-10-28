package com.ytell.zhiyuan.web.interceptor;

public class UserInfoThreadLocalUtil {
    private final static ThreadLocal<UserBaseData> threadLocal = new ThreadLocal<UserBaseData>();

    /**
     * 设置数据到当前线程
     */
    public static void set(UserBaseData o) {
        if (o == null) {
            threadLocal.remove();
        } else {
            threadLocal.set(o);
        }
    }

    /**
     * 获取线程中的数据
     *
     * @return
     */
    public static UserBaseData get() {
        return threadLocal.get();
    }

    public static void remove() {
        threadLocal.remove();
    }


}
