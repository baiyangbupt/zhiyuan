package com.ytell.zhiyuan.common.config;

import com.ytell.zhiyuan.web.interceptor.ControllerTimingInterceptor;
import com.ytell.zhiyuan.web.interceptor.LoginInterceptor;
import com.ytell.zhiyuan.web.interceptor.TraceIdInterceptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.*;

@Configuration
@EnableWebMvc
public class WebConfig implements WebMvcConfigurer {
    @Autowired
    ControllerTimingInterceptor controllerTimingInterceptor;
    @Autowired
    private TraceIdInterceptor traceIdInterceptor;
    @Autowired
    private LoginInterceptor loginInterceptor;

    @Override
    public void configureDefaultServletHandling(DefaultServletHandlerConfigurer configurer) {
        configurer.enable();
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/doc.html").addResourceLocations("classpath:/META-INF/resources/");
        registry.addResourceHandler("swagger-ui.html").addResourceLocations("classpath:/META-INF/resources/");
        registry.addResourceHandler("/webjars/**").addResourceLocations("classpath:/META-INF/resources/webjars/");
        registry.addResourceHandler("/**").addResourceLocations("classpath:/static/");
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        //统计接口响应时间
        registry.addInterceptor(controllerTimingInterceptor).addPathPatterns("/**");
        //traceId
        registry.addInterceptor(traceIdInterceptor).addPathPatterns("/**");
        //需要登录
        registry.addInterceptor(loginInterceptor).addPathPatterns("/**")
                .excludePathPatterns(
                        "/**/admin/**",
                        "/**/inner/**",
                        "/**/user/login/**",
                        "/**/wx/**",
                        "/**/debug/**",
                        "/**/base-data/**",
                        // Swagger相关路径 (SpringFox 2.7.0)
                        "/doc.html",
                        "/swagger-ui.html",
                        "/swagger-resources/**",
                        "/swagger-resources",
                        "/webjars/**",
                        "/v2/api-docs",
                        "/v2/api-docs/**",
                        "/swagger-ui/**",
                        "/swagger/**",
                        "/configuration/ui",
                        "/configuration/security",
                        "/error"
                );

    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                .allowedHeaders("*")
                .allowedMethods("*")
                .allowedOrigins("*");
    }

}
