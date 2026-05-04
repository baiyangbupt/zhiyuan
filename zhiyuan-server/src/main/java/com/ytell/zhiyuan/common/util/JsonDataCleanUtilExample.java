package com.ytell.zhiyuan.common.util;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import lombok.extern.slf4j.Slf4j;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * JsonDataCleanUtil 使用示例
 * 演示如何使用字符串字段加工功能
 */
@Slf4j
public class JsonDataCleanUtilExample {

    public static void main(String[] args) {
        // 综合示例：覆盖所有功能的复杂测试
        comprehensiveExample();
    }

    /**
     * 综合示例：覆盖所有功能的复杂测试
     * 包含删除字段、重命名字段、字符串处理、嵌套路径、字段名匹配等各种情况
     */
    private static void comprehensiveExample() {
        log.info("=== 综合示例：JsonDataCleanUtil 全功能测试 ===");

        // 复杂的原始JSON数据 - 包含多层嵌套、数组、各种字段类型
        String jsonStr = "{\n" +
                "    \"company_info\": {\n" +
                "        \"company_name\": \"高途科技集团\",\n" +
                "        \"company_score\": \"95.5\",\n" +
                "        \"company_level\": \"A+\",\n" +
                "        \"contact_info\": {\n" +
                "            \"phone\": \"010-12345678\",\n" +
                "            \"email\": \"contact@gaotu.com\",\n" +
                "            \"address\": \"北京市朝阳区\"\n" +
                "        },\n" +
                "        \"temp_data\": \"临时数据\",\n" +
                "        \"departments\": [\n" +
                "            {\n" +
                "                \"dept_name\": \"技术研发部\",\n" +
                "                \"dept_score\": \"92%\",\n" +
                "                \"dept_level\": \"S\",\n" +
                "                \"dept_size\": \"150\",\n" +
                "                \"manager_info\": {\n" +
                "                    \"manager_name\": \"张技术总监\",\n" +
                "                    \"manager_phone\": \"13800138000\",\n" +
                "                    \"manager_salary\": \"50000.5\",\n" +
                "                    \"manager_age\": \"35\",\n" +
                "                    \"manager_score\": \"98%\"\n" +
                "                },\n" +
                "                \"employees\": [\n" +
                "                    {\n" +
                "                        \"emp_name\": \"李程序员\",\n" +
                "                        \"emp_score\": \"88%\",\n" +
                "                        \"emp_level\": \"A\",\n" +
                "                        \"emp_salary\": \"25000.8\",\n" +
                "                        \"emp_age\": \"28\",\n" +
                "                        \"emp_phone\": \"13900139000\",\n" +
                "                        \"emp_skills\": [\"Java\", \"Python\", \"Vue\"],\n" +
                "                        \"performance\": {\n" +
                "                            \"perf_name\": \"年度绩效\",\n" +
                "                            \"perf_score\": \"85.5\",\n" +
                "                            \"perf_level\": \"B+\",\n" +
                "                            \"perf_rating\": \"4.2\"\n" +
                "                        }\n" +
                "                    },\n" +
                "                    {\n" +
                "                        \"emp_name\": \"王架构师\",\n" +
                "                        \"emp_score\": \"95%\",\n" +
                "                        \"emp_level\": \"S\",\n" +
                "                        \"emp_salary\": \"45000.2\",\n" +
                "                        \"emp_age\": \"32\",\n" +
                "                        \"emp_phone\": \"13700137000\",\n" +
                "                        \"emp_skills\": [\"架构设计\", \"微服务\", \"云原生\"],\n" +
                "                        \"performance\": {\n" +
                "                            \"perf_name\": \"年度绩效\",\n" +
                "                            \"perf_score\": \"96.8\",\n" +
                "                            \"perf_level\": \"A+\",\n" +
                "                            \"perf_rating\": \"4.8\"\n" +
                "                        }\n" +
                "                    }\n" +
                "                ]\n" +
                "            },\n" +
                "            {\n" +
                "                \"dept_name\": \"销售部\",\n" +
                "                \"dept_score\": \"87%\",\n" +
                "                \"dept_level\": \"A\",\n" +
                "                \"dept_size\": \"80\",\n" +
                "                \"manager_info\": {\n" +
                "                    \"manager_name\": \"赵销售总监\",\n" +
                "                    \"manager_phone\": \"13600136000\",\n" +
                "                    \"manager_salary\": \"40000.0\",\n" +
                "                    \"manager_age\": \"38\",\n" +
                "                    \"manager_score\": \"92%\"\n" +
                "                },\n" +
                "                \"employees\": [\n" +
                "                    {\n" +
                "                        \"emp_name\": \"钱销售员\",\n" +
                "                        \"emp_score\": \"82%\",\n" +
                "                        \"emp_level\": \"B\",\n" +
                "                        \"emp_salary\": \"18000.5\",\n" +
                "                        \"emp_age\": \"25\",\n" +
                "                        \"emp_phone\": \"13500135000\",\n" +
                "                        \"emp_skills\": [\"客户管理\", \"谈判技巧\"],\n" +
                "                        \"performance\": {\n" +
                "                            \"perf_name\": \"季度绩效\",\n" +
                "                            \"perf_score\": \"78.5\",\n" +
                "                            \"perf_level\": \"C+\",\n" +
                "                            \"perf_rating\": \"3.5\"\n" +
                "                        }\n" +
                "                    }\n" +
                "                ]\n" +
                "            }\n" +
                "        ]\n" +
                "    },\n" +
                "    \"extra_info\": \"额外信息\",\n" +
                "    \"temp_cache\": \"临时缓存\",\n" +
                "    \"system_config\": {\n" +
                "        \"config_name\": \"系统配置\",\n" +
                "        \"config_version\": \"1.2.3\",\n" +
                "        \"config_score\": \"99%\"\n" +
                "    }\n" +
                "}";

        JSONObject jsonObject = JSON.parseObject(jsonStr);

        // 1. 配置要删除的字段 - 支持字段名匹配和嵌套路径匹配
        List<String> removeFields = Arrays.asList(
                "extra_info",                                    // 删除顶级字段
                "temp_cache",                                    // 删除顶级字段
                "temp_data",                                     // 删除嵌套字段
                "phone",                                         // 删除所有层级的phone字段
                "emp_phone",                                     // 删除所有员工电话
                "emp_skills",                                    // 删除所有员工技能列表
                "company_info.departments.employees.emp_level",  // 删除嵌套路径：员工等级
                "company_info.departments.dept_size"            // 删除嵌套路径：部门人数
        );

        // 2. 配置字段重命名 - 支持字段名匹配和嵌套路径匹配
        Map<String, String> fieldMappings = new HashMap<>();
        // 字段名匹配（所有层级）
        fieldMappings.put("company_name", "name");
        fieldMappings.put("dept_name", "name");
        fieldMappings.put("emp_name", "name");
        fieldMappings.put("manager_name", "name");
        fieldMappings.put("perf_name", "name");
        fieldMappings.put("config_name", "name");

        // 嵌套路径匹配（精确控制）
        fieldMappings.put("company_info.company_name", "companyName");
        fieldMappings.put("company_info.departments.dept_name", "departmentName");
        fieldMappings.put("company_info.departments.employees.emp_name", "employeeName");
        fieldMappings.put("company_info.departments.manager_info.manager_name", "managerName");
        fieldMappings.put("company_info.departments.employees.performance.perf_name", "performanceName");

        // 3. 配置字符串处理器 - 支持字段名匹配和嵌套路径匹配
        Map<String, JsonDataCleanUtil.StringProcessor> stringProcessors = new HashMap<>();
        // 字段名匹配（所有层级）
        stringProcessors.put("score", JsonDataCleanUtil.PERCENTAGE_PROCESSOR);           // 所有score字段转百分比整数
        stringProcessors.put("age", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);          // 所有age字段转整数
        stringProcessors.put("rating", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);       // 所有rating字段转整数

        // 嵌套路径匹配（精确控制）
        stringProcessors.put("company_info.company_score", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);  // 公司分数转整数
        stringProcessors.put("company_info.departments.dept_score", JsonDataCleanUtil.PERCENTAGE_PROCESSOR);  // 部门分数转百分比整数
        stringProcessors.put("company_info.departments.manager_info.manager_salary", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);  // 经理薪资转整数
        stringProcessors.put("company_info.departments.employees.emp_salary", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);  // 员工薪资转整数
        stringProcessors.put("company_info.departments.employees.performance.perf_score", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);  // 绩效分数转整数

        // 处理数据
        Object result = JsonDataCleanUtil.cleanJsonDataWithStringProcessing(
                jsonObject,
                removeFields,
                fieldMappings,
                stringProcessors
        );

        log.info("原始数据: {}", jsonStr);
        log.info("处理后: {}", JSON.toJSONString(result, true));
        log.info("");
        log.info("=== 处理说明 ===");
        log.info("1. 删除字段:");
        log.info("   - 顶级字段: extra_info, temp_cache");
        log.info("   - 嵌套字段: temp_data");
        log.info("   - 字段名匹配: phone, emp_phone, emp_skills");
        log.info("   - 嵌套路径: company_info.departments.employees.emp_level, company_info.departments.dept_size");
        log.info("");
        log.info("2. 重命名字段:");
        log.info("   - 字段名匹配: company_name→name, dept_name→name, emp_name→name, manager_name→name, perf_name→name, config_name→name");
        log.info("   - 嵌套路径优先: company_info.company_name→companyName, company_info.departments.dept_name→departmentName, company_info.departments.employees.emp_name→employeeName");
        log.info("");
        log.info("3. 字符串处理:");
        log.info("   - 字段名匹配: score(百分比), age(转整数), rating(转整数)");
        log.info("   - 嵌套路径优先: company_score(转整数), dept_score(百分比), manager_salary(转整数), emp_salary(转整数), perf_score(转整数)");
        log.info("");
        log.info("4. 优先级规则: 嵌套路径匹配 > 字段名匹配");
        log.info("5. 支持功能: 删除、重命名、字符串处理、嵌套路径、字段名匹配、数组处理");
        log.info("");
    }
}
