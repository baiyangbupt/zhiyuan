package com.ytell.zhiyuan.common.util;

import cn.hutool.core.io.FileUtil;
import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.TypeReference;
import lombok.extern.slf4j.Slf4j;
import okhttp3.*;
import org.springframework.lang.Nullable;
import org.springframework.util.StreamUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@Slf4j
public class JsonHttpUtil {

    /**
     * 默认连接超时时间（毫秒）.
     */
    static final long DEFAULT_CONNECT_TIMEOUT_MILLS = 5000L;
    /**
     * 默认读取超时时间（毫秒）
     */
    static final long DEFAULT_READ_TIMEOUT_MILLS = 20000L;
    /**
     * 默认写出超时时间（毫秒）
     */
    static final long DEFAULT_WRITE_TIMEOUT_MILLS = 20000L;
    /**
     * 请求体类型
     */
    static final MediaType JSONType = MediaType.parse("application/json; charset=utf-8");

    /**
     * 全局单例
     */
    private static final OkHttpClient Client = new OkHttpClient.Builder()
            .connectTimeout(DEFAULT_CONNECT_TIMEOUT_MILLS, TimeUnit.MILLISECONDS)
            .readTimeout(DEFAULT_READ_TIMEOUT_MILLS, TimeUnit.MILLISECONDS)
            .writeTimeout(DEFAULT_WRITE_TIMEOUT_MILLS, TimeUnit.MILLISECONDS)
            .connectionPool(new ConnectionPool(5, 5, TimeUnit.MINUTES))
            .build();

    private JsonHttpUtil() {
    }

    /**
     * 发送GET请求并处理泛型响应
     *
     * @param url           请求URL
     * @param params        请求参数
     * @param headers       请求头
     * @param typeReference 响应类型引用
     * @param <T>           响应类型
     * @return 泛型响应对象
     */
    public static <T> T get(String url, Map<String, Object> params, Map<String, String> headers, TypeReference<T> typeReference) {
        Request.Builder builder = new Request.Builder();
        HttpUrl.Builder urlBuilder = HttpUrl.parse(url).newBuilder();

        if (params != null) {
            for (String key : params.keySet()) {
                Object value = params.get(key);
                if (value != null) {
                    urlBuilder.addQueryParameter(key, String.valueOf(value));
                }
            }
        }

        // 添加请求头
        if (headers != null) {
            for (Map.Entry<String, String> entry : headers.entrySet()) {
                builder.addHeader(entry.getKey(), entry.getValue());
            }
        }

        Request request = builder
                .url(urlBuilder.build())
                .get()
                .build();

        return execute(request, typeReference);
    }

    /**
     * 发送GET请求并处理泛型响应（无header版本，向后兼容）
     */
    public static <T> T get(String url, Map<String, Object> params, TypeReference<T> typeReference) {
        return get(url, params, null, typeReference);
    }

    /**
     * 发送POST JSON请求并处理泛型响应
     *
     * @param url           请求URL
     * @param bodyOb        请求参数
     * @param headers       请求头
     * @param typeReference 响应类型引用
     * @param <T>           响应类型
     * @return 泛型响应对象
     */
    public static <T> T post(String url, Object bodyOb, Map<String, String> headers, TypeReference<T> typeReference) {
        Request.Builder builder = new Request.Builder();
        String paramsJsonStr = JSON.toJSONString(bodyOb);
        RequestBody body = RequestBody.create(paramsJsonStr, JSONType);

        // 添加请求头
        if (headers != null) {
            for (Map.Entry<String, String> entry : headers.entrySet()) {
                builder.addHeader(entry.getKey(), entry.getValue());
            }
        }

        Request request = builder
                .url(url)
                .post(body)
                .build();

        return execute(request, typeReference);
    }

    /**
     * 发送POST JSON请求并处理泛型响应（无header版本，向后兼容）
     */
    public static <T> T post(String url, Object bodyOb, TypeReference<T> typeReference) {
        return post(url, bodyOb, null, typeReference);
    }

    /**
     * 执行HTTP请求并处理泛型响应
     */
    @Nullable
    private static <T> T execute(Request request, TypeReference<T> typeReference) {
        String host = request.url().host() + ":" + request.url().port();
        String uri = request.url().encodedPath();
        String query = request.url().query();
        long before = System.currentTimeMillis();

        try (Response response = Client.newCall(request).execute()) {
            long after = System.currentTimeMillis();
            if (response.code() != 200) {
                log.warn("_com_http_failure host={}||uri={}||query={}||proc_time={}ms||code={}", host, uri, query, (after - before),
                        response.code());
                throw new RuntimeException("invoke HTTP fail");
            }

            ResponseBody body = response.body();
            String retStr = body == null ? "" : StreamUtils.copyToString(body.byteStream(), StandardCharsets.UTF_8);
            log.debug("_com_http_success host={}||uri={}||query={}||proc_time={}ms||{}", host, uri, query, (after - before), retStr);

            if (retStr == null || retStr.isEmpty()) {
                return null;
            }

            try {
                return JSON.parseObject(retStr, typeReference);
            } catch (Exception e) {
                log.error("invoke HTTP success, but parse to obj err", e);
                throw new RuntimeException("Parse response failed", e);
            }
        } catch (IOException e) {
            log.error("invoke HTTP error: {}", uri, e);
            throw new RuntimeException("invoke HTTP error", e);
        }
    }

    public static void main(String[] args) {
        String origin = "CREATE TABLE `user_school_plan_snap_%s` (\n" +
                "                                         `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '主键ID',\n" +
                "                                         `member_id` bigint(20) DEFAULT NULL COMMENT '用户ID',\n" +
                "                                         `session_id` bigint(20) DEFAULT NULL COMMENT '会话ID',\n" +
                "                                         `school_id` varchar(32) DEFAULT NULL COMMENT '院校ID',\n" +
                "                                         `plan_school_data_id` varchar(32) DEFAULT NULL COMMENT '院校招生数据ID，保存方案时前端需要传参',\n" +
                "                                         `school_unit_name` varchar(512) DEFAULT NULL COMMENT '招生单位名称',\n" +
                "                                         `school_unit_code` varchar(32) DEFAULT NULL COMMENT '招生单位代码',\n" +
                "                                         `tag` varchar(255) DEFAULT NULL COMMENT '院校标签code列表',\n" +
                "                                         `tag_list` json DEFAULT NULL COMMENT '院校标签列表',\n" +
                "                                         `classify_list` json DEFAULT NULL COMMENT '院校分类',\n" +
                "                                         `area_code` varchar(32) DEFAULT NULL COMMENT '省份code',\n" +
                "                                         `area_name` varchar(32) DEFAULT NULL COMMENT '省份名称',\n" +
                "                                         `city_code` varchar(32) DEFAULT NULL COMMENT '城市code',\n" +
                "                                         `city_name` varchar(32) DEFAULT NULL COMMENT '城市名称',\n" +
                "                                         `school_type_code` varchar(32) DEFAULT NULL COMMENT '院校类型code',\n" +
                "                                         `school_type_name` varchar(64) DEFAULT NULL COMMENT '院校类型名称',\n" +
                "                                         `school_address` varchar(512) DEFAULT NULL COMMENT '院校地址',\n" +
                "                                         `school_enroll_ratio` int(11) DEFAULT NULL COMMENT '院校录取概率',\n" +
                "                                         `school_enroll_advice` varchar(255) DEFAULT NULL COMMENT '院校填报建议',\n" +
                "                                         `school_volunteer_level_code` varchar(32) DEFAULT NULL COMMENT '院校数据类型，SPRINT-冲，SAFE-稳，PROTECT-保',\n" +
                "                                         `school_volunteer_level_name` varchar(32) DEFAULT NULL COMMENT '院校数据类型，SPRINT-冲，SAFE-稳，PROTECT-保',\n" +
                "                                         `school_is_new` tinyint(1) DEFAULT '0' COMMENT '是否为新增院校',\n" +
                "                                         `school_level_code` varchar(32) DEFAULT NULL COMMENT '院校层级code',\n" +
                "                                         `school_level_name` varchar(64) DEFAULT NULL COMMENT '院校层级名称',\n" +
                "                                         `major_count` int(11) DEFAULT NULL COMMENT '专业数',\n" +
                "                                         `major_id` varchar(32) DEFAULT NULL COMMENT '专业Id',\n" +
                "                                         `major_name` varchar(512) DEFAULT NULL COMMENT '专业名称',\n" +
                "                                         `plan_major_data_id` varchar(32) DEFAULT NULL COMMENT '专业招生计划ID',\n" +
                "                                         `major_unit_name` varchar(512) DEFAULT NULL COMMENT '专业名称',\n" +
                "                                         `major_is_new` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否新增专业',\n" +
                "                                         `is_double_first_major` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否双一流专业',\n" +
                "                                         `increase_num` int(11) NOT NULL DEFAULT '0' COMMENT '增加数量',\n" +
                "                                         `major_volunteer_level_code` varchar(32) DEFAULT NULL COMMENT '专业数据类型，SPRINT-冲，SAFE-稳，PROTECT-保',\n" +
                "                                         `major_volunteer_level_name` varchar(64) DEFAULT NULL COMMENT '专业数据类型，SPRINT-冲，SAFE-稳，PROTECT-保',\n" +
                "                                         `enroll_ratio` int(11)  DEFAULT NULL COMMENT '专业录取概率',\n" +
                "                                         `enroll_advice` varchar(512) DEFAULT NULL COMMENT '专业填报建议',\n" +
                "                                         `semang_special` tinyint(1) NOT NULL DEFAULT '1' COMMENT '色盲色弱可报:0：不可报，1：可报',\n" +
                "                                         `zhuanxiang_special` tinyint(1) NOT NULL DEFAULT '0' COMMENT '专项计划要求：0，不要求；1，要求',\n" +
                "                                         `school_pos` bigint(20) DEFAULT NULL COMMENT '院校位置',\n" +
                "                                         `category_id` varchar(32) DEFAULT NULL COMMENT '类别ID',\n" +
                "                                         `sub_category_id` varchar(32) DEFAULT NULL COMMENT '子类别ID',\n" +
                "                                         `select_info` varchar(32) DEFAULT NULL COMMENT '选择信息',\n" +
                "                                         `money` bigint(20) DEFAULT NULL COMMENT '金额',\n" +
                "                                         `major_pos` bigint(20) DEFAULT NULL COMMENT '专业位置',\n" +
                "                                         `plan_num` int(11) DEFAULT NULL COMMENT '计划数量',\n" +
                "                                         `major_score` bigint(20) DEFAULT NULL COMMENT '专业分数',\n" +
                "                                         `major_unit_code` varchar(32) DEFAULT NULL COMMENT '专业单位代码',\n" +
                "                                         `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',\n" +
                "                                         `update_time` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',\n" +
                "                                         PRIMARY KEY (`id`),\n" +
                "                                         UNIQUE KEY `unique_member_session_school_major` (\n" +
                "                                             `member_id`,\n" +
                "                                             `session_id`,\n" +
                "                                             `plan_school_data_id`,\n" +
                "                                             `plan_major_data_id`\n" +
                "                                             ),\n" +
                "                                         KEY `idx_session_id` (`session_id`)\n" +
                ") ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '院校填报计划表';";

        String result = "";

        for (int i = 0; i < 100; i++) {
            String one = String.format(origin, i);
            result = result + "\n" + one;
        }

        FileUtil.appendUtf8String(result, "/Users/huqitong/Documents/yuzhi/sales-bot-server/script/db/2025-04-14.sql");

    }
}