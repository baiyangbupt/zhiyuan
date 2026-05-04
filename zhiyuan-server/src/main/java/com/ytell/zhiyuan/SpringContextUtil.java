package com.ytell.zhiyuan;

import org.springframework.beans.BeansException;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationContextAware;
import org.springframework.stereotype.Component;

import java.util.Locale;
import java.util.Map;

@Component("springContextUtil")
public class SpringContextUtil implements ApplicationContextAware {

    private static ApplicationContext context;

    /**
     * 根据name获取bean
     *
     * @param beanName
     * @param <T>
     * @return
     */
    public static <T> T getBean(String beanName) {
        return (T) context.getBean(beanName);
    }

    /**
     * 根据type获取bean
     *
     * @param t
     * @param <T>
     * @return
     */
    public static <T> Map<String, T> getBeansOfType(Class<T> t) {
        return context.getBeansOfType(t);
    }

    /**
     * 国际化使用
     *
     * @param key
     * @return
     */

    public static String getMessage(String key) {
        return context.getMessage(key, null, Locale.getDefault());
    }

    /**
     * 获取当前环境
     *
     * @return
     */
    public static String getActiveProfile() {
        return context.getEnvironment().getActiveProfiles()[0];
    }

    @Override
    public void setApplicationContext(ApplicationContext applicationContext) throws BeansException {
        SpringContextUtil.context = applicationContext;
    }
}
