package com.ytell.zhiyuan.common.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.DynamicTableNameInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import lombok.extern.slf4j.Slf4j;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * @author huqitong
 * @version 1.0
 */
@Configuration
@MapperScan("com.ytell.zhiyuan.mapper*")
@Slf4j
public class MybatisPlusConfig {
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        DynamicTableNameInnerInterceptor dynamicTableNameInnerInterceptor = new DynamicTableNameInnerInterceptor();
        dynamicTableNameInnerInterceptor.setTableNameHandler((sql, tableName) -> {
            //  用户专业计划快照需要分表查
            if (tableName.equals("user_school_plan_snap")) {
                String suffix = DynamicDBTableHelper.getSuffix();
                log.info("user_school_plan_snap:suffix:{}", suffix);
                return tableName + "_" + suffix;
            } else {
                return tableName;
            }
        });
        interceptor.addInnerInterceptor(dynamicTableNameInnerInterceptor);
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }

}