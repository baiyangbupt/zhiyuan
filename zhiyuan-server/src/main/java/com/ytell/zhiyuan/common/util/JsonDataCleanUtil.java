package com.ytell.zhiyuan.common.util;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import lombok.extern.slf4j.Slf4j;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * JSON数据清洗工具类
 * 用于清洗和简化gaotuClient.getProgramFullList返回的数据
 * 支持字段删除和字段重命名，包括嵌套字段路径（a.b.c格式）
 * 支持嵌套字段打平功能
 */
@Slf4j
public class JsonDataCleanUtil {

    /**
     * 预定义的处理器实例
     */
    public static final StringProcessor PERCENTAGE_PROCESSOR = new PercentageProcessor();
    public static final StringProcessor FLOAT_TO_INT_PROCESSOR = new FloatToIntProcessor();

    /**
     * 清洗JSON数据
     *
     * @param jsonObject    原始JSON对象
     * @param removeFields  需要删除的字段列表，支持a.b.c格式的嵌套字段
     * @param fieldMappings 字段重命名映射，key为原字段名，value为新字段名，支持a.b.c格式
     * @return 清洗后的JSON数据字符串
     */
    public static Object cleanJsonData(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings) {
        try {
            Object cleanedObject = cleanJsonObject(jsonObject, removeFields, fieldMappings);
            return cleanedObject;
        } catch (Exception e) {
            log.error("清洗JSON数据失败", e);
            return jsonObject;
        }
    }

    /**
     * 清洗JSON数据（支持嵌套字段打平）
     *
     * @param jsonObject      原始JSON数据字符串
     * @param removeFields    需要删除的字段列表
     * @param fieldMappings   字段重命名映射
     * @param flattenMappings 嵌套字段打平映射，key为嵌套路径，value为新的顶级字段名
     * @return 清洗后的JSON数据字符串
     */
    public static Object cleanJsonData(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings) {
        try {
            Object cleanedObject = cleanJsonObjectWithFlatten(jsonObject, removeFields, fieldMappings, flattenMappings);
            return cleanedObject;
        } catch (Exception e) {
            log.error("清洗JSON数据失败", e);
            return jsonObject;
        }
    }

    /**
     * 清洗JSON对象
     *
     * @param jsonObject    原始JSON对象
     * @param removeFields  需要删除的字段列表
     * @param fieldMappings 字段重命名映射
     * @return 清洗后的JSON对象
     */
    private static Object cleanJsonObject(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings) {
        if (jsonObject == null) {
            return null;
        }

        if (jsonObject instanceof JSONObject) {
            return cleanJsonObject((JSONObject) jsonObject, removeFields, fieldMappings, "");
        } else if (jsonObject instanceof JSONArray) {
            return cleanJsonArray((JSONArray) jsonObject, removeFields, fieldMappings, "");
        } else {
            return jsonObject;
        }
    }

    /**
     * 清洗JSON对象（支持嵌套字段打平）
     */
    private static Object cleanJsonObjectWithFlatten(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings) {
        if (jsonObject == null) {
            return null;
        }

        if (jsonObject instanceof JSONObject) {
            return cleanJsonObjectWithFlatten((JSONObject) jsonObject, removeFields, fieldMappings, flattenMappings, "");
        } else if (jsonObject instanceof JSONArray) {
            return cleanJsonArrayWithFlatten((JSONArray) jsonObject, removeFields, fieldMappings, flattenMappings, "");
        } else {
            return jsonObject;
        }
    }

    /**
     * 清洗JSONObject
     */
    private static JSONObject cleanJsonObject(JSONObject jsonObject, List<String> removeFields, Map<String, String> fieldMappings, String currentPath) {
        JSONObject result = new JSONObject();

        for (Map.Entry<String, Object> entry : jsonObject.entrySet()) {
            String key = entry.getKey();
            Object value = entry.getValue();

            // 构建当前字段的完整路径
            String fieldPath = currentPath.isEmpty() ? key : currentPath + "." + key;

            // 检查是否需要删除该字段
            if (shouldRemoveField(fieldPath, removeFields)) {
                continue;
            }

            // 获取新的字段名
            String newKey = getNewFieldName(key, fieldPath, fieldMappings);

            // 递归处理嵌套对象
            if (value instanceof JSONObject) {
                value = cleanJsonObject((JSONObject) value, removeFields, fieldMappings, fieldPath);
            } else if (value instanceof JSONArray) {
                value = cleanJsonArray((JSONArray) value, removeFields, fieldMappings, fieldPath);
            }

            result.put(newKey, value);
        }

        return result;
    }

    /**
     * 清洗JSONObject（支持嵌套字段打平）
     */
    private static JSONObject cleanJsonObjectWithFlatten(JSONObject jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings, String currentPath) {
        JSONObject result = new JSONObject();
        Map<String, Object> flattenedFields = new HashMap<>();

        for (Map.Entry<String, Object> entry : jsonObject.entrySet()) {
            String key = entry.getKey();
            Object value = entry.getValue();

            // 构建当前字段的完整路径
            String fieldPath = currentPath.isEmpty() ? key : currentPath + "." + key;

            // 检查是否需要删除该字段
            if (shouldRemoveField(fieldPath, removeFields)) {
                continue;
            }

            // 检查是否需要打平该字段
            if (flattenMappings != null && flattenMappings.containsKey(fieldPath)) {
                String flattenedKey = flattenMappings.get(fieldPath);
                flattenedFields.put(flattenedKey, value);
                continue;
            }

            // 获取新的字段名
            String newKey = getNewFieldName(key, fieldPath, fieldMappings);

            // 递归处理嵌套对象
            if (value instanceof JSONObject) {
                value = cleanJsonObjectWithFlatten((JSONObject) value, removeFields, fieldMappings, flattenMappings, fieldPath);
            } else if (value instanceof JSONArray) {
                value = cleanJsonArrayWithFlatten((JSONArray) value, removeFields, fieldMappings, flattenMappings, fieldPath);
            }

            result.put(newKey, value);
        }

        // 添加打平的字段到结果中
        result.putAll(flattenedFields);

        return result;
    }

    /**
     * 清洗JSONArray
     */
    private static JSONArray cleanJsonArray(JSONArray jsonArray, List<String> removeFields, Map<String, String> fieldMappings, String currentPath) {
        JSONArray result = new JSONArray();

        for (int i = 0; i < jsonArray.size(); i++) {
            Object item = jsonArray.get(i);
            Object cleanedItem;

            if (item instanceof JSONObject) {
                cleanedItem = cleanJsonObject((JSONObject) item, removeFields, fieldMappings, currentPath);
            } else if (item instanceof JSONArray) {
                cleanedItem = cleanJsonArray((JSONArray) item, removeFields, fieldMappings, currentPath);
            } else {
                cleanedItem = item;
            }

            result.add(cleanedItem);
        }

        return result;
    }

    /**
     * 清洗JSONArray（支持嵌套字段打平）
     */
    private static JSONArray cleanJsonArrayWithFlatten(JSONArray jsonArray, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings, String currentPath) {
        JSONArray result = new JSONArray();

        for (int i = 0; i < jsonArray.size(); i++) {
            Object item = jsonArray.get(i);
            Object cleanedItem;

            if (item instanceof JSONObject) {
                cleanedItem = cleanJsonObjectWithFlatten((JSONObject) item, removeFields, fieldMappings, flattenMappings, currentPath);
            } else if (item instanceof JSONArray) {
                cleanedItem = cleanJsonArrayWithFlatten((JSONArray) item, removeFields, fieldMappings, flattenMappings, currentPath);
            } else {
                cleanedItem = item;
            }

            result.add(cleanedItem);
        }

        return result;
    }

    /**
     * 检查字段是否应该被删除
     * 支持嵌套字段路径匹配
     */
    private static boolean shouldRemoveField(String fieldPath, List<String> removeFields) {
        if (removeFields == null || removeFields.isEmpty()) {
            return false;
        }

        // 直接匹配完整路径
        if (removeFields.contains(fieldPath)) {
            return true;
        }

        // 匹配字段名（不包含路径）
        String fieldName = fieldPath.contains(".") ? fieldPath.substring(fieldPath.lastIndexOf(".") + 1) : fieldPath;
        return removeFields.contains(fieldName);
    }

    /**
     * 获取新的字段名
     * 支持嵌套字段路径匹配
     */
    private static String getNewFieldName(String originalName, Map<String, String> fieldMappings) {
        if (fieldMappings == null || fieldMappings.isEmpty()) {
            return originalName;
        }

        // 直接匹配字段名
        return fieldMappings.getOrDefault(originalName, originalName);
    }

    /**
     * 获取新的字段名（支持完整路径）
     * 支持嵌套字段路径匹配
     */
    private static String getNewFieldName(String originalName, String fieldPath, Map<String, String> fieldMappings) {
        if (fieldMappings == null || fieldMappings.isEmpty()) {
            return originalName;
        }

        // 1. 直接匹配完整路径
        if (fieldMappings.containsKey(fieldPath)) {
            return fieldMappings.get(fieldPath);
        }

        // 2. 匹配字段名（不包含路径）
        return fieldMappings.getOrDefault(originalName, originalName);
    }

    /**
     * 获取字符串处理器
     * 支持完整路径匹配和字段名匹配
     */
    private static StringProcessor getStringProcessor(String fieldPath, Map<String, StringProcessor> stringProcessors) {
        if (stringProcessors == null || stringProcessors.isEmpty()) {
            return null;
        }

        // 1. 直接匹配完整路径
        if (stringProcessors.containsKey(fieldPath)) {
            return stringProcessors.get(fieldPath);
        }

        // 2. 匹配字段名（不包含路径）
        String fieldName = fieldPath.contains(".") ? fieldPath.substring(fieldPath.lastIndexOf(".") + 1) : fieldPath;
        return stringProcessors.get(fieldName);
    }

    /**
     * 清洗JSON数据（支持字符串字段加工）
     *
     * @param jsonObject       原始JSON对象
     * @param removeFields     需要删除的字段列表，支持a.b.c格式的嵌套字段
     * @param fieldMappings    字段重命名映射，key为原字段名，value为新字段名，支持a.b.c格式
     * @param stringProcessors 字符串字段处理器映射，key为字段路径，value为处理器类型
     * @return 清洗后的JSON数据
     */
    public static Object cleanJsonDataWithStringProcessing(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, StringProcessor> stringProcessors) {
        try {
            Object cleanedObject = cleanJsonObjectWithStringProcessing(jsonObject, removeFields, fieldMappings, stringProcessors);
            return cleanedObject;
        } catch (Exception e) {
            log.error("清洗JSON数据失败", e);
            return jsonObject;
        }
    }

    /**
     * 清洗JSON数据（支持嵌套字段打平和字符串字段加工）
     *
     * @param jsonObject       原始JSON数据
     * @param removeFields     需要删除的字段列表
     * @param fieldMappings    字段重命名映射
     * @param flattenMappings  嵌套字段打平映射，key为嵌套路径，value为新的顶级字段名
     * @param stringProcessors 字符串字段处理器映射，key为字段路径，value为处理器类型
     * @return 清洗后的JSON数据
     */
    public static Object cleanJsonDataWithFlattenAndStringProcessing(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings, Map<String, StringProcessor> stringProcessors) {
        try {
            Object cleanedObject = cleanJsonObjectWithFlattenAndStringProcessing(jsonObject, removeFields, fieldMappings, flattenMappings, stringProcessors);
            return cleanedObject;
        } catch (Exception e) {
            log.error("清洗JSON数据失败", e);
            return jsonObject;
        }
    }

    /**
     * 清洗JSON对象（支持字符串字段加工）
     */
    private static Object cleanJsonObjectWithStringProcessing(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, StringProcessor> stringProcessors) {
        if (jsonObject == null) {
            return null;
        }

        if (jsonObject instanceof JSONObject) {
            return cleanJsonObjectWithStringProcessing((JSONObject) jsonObject, removeFields, fieldMappings, stringProcessors, "");
        } else if (jsonObject instanceof JSONArray) {
            return cleanJsonArrayWithStringProcessing((JSONArray) jsonObject, removeFields, fieldMappings, stringProcessors, "");
        } else {
            return jsonObject;
        }
    }

    /**
     * 清洗JSON对象（支持嵌套字段打平和字符串字段加工）
     */
    private static Object cleanJsonObjectWithFlattenAndStringProcessing(Object jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings, Map<String, StringProcessor> stringProcessors) {
        if (jsonObject == null) {
            return null;
        }

        if (jsonObject instanceof JSONObject) {
            return cleanJsonObjectWithFlattenAndStringProcessing((JSONObject) jsonObject, removeFields, fieldMappings, flattenMappings, stringProcessors, "");
        } else if (jsonObject instanceof JSONArray) {
            return cleanJsonArrayWithFlattenAndStringProcessing((JSONArray) jsonObject, removeFields, fieldMappings, flattenMappings, stringProcessors, "");
        } else {
            return jsonObject;
        }
    }

    /**
     * 清洗JSONObject（支持字符串字段加工）
     */
    private static JSONObject cleanJsonObjectWithStringProcessing(JSONObject jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, StringProcessor> stringProcessors, String currentPath) {
        JSONObject result = new JSONObject();

        for (Map.Entry<String, Object> entry : jsonObject.entrySet()) {
            String key = entry.getKey();
            Object value = entry.getValue();

            // 构建当前字段的完整路径
            String fieldPath = currentPath.isEmpty() ? key : currentPath + "." + key;

            // 检查是否需要删除该字段
            if (shouldRemoveField(fieldPath, removeFields)) {
                continue;
            }

            // 获取新的字段名
            String newKey = getNewFieldName(key, fieldPath, fieldMappings);

            // 处理字符串字段加工
            if (stringProcessors != null && value instanceof String) {
                StringProcessor processor = getStringProcessor(fieldPath, stringProcessors);
                if (processor != null) {
                    value = processor.process((String) value);
                }
            }

            // 递归处理嵌套对象
            if (value instanceof JSONObject) {
                value = cleanJsonObjectWithStringProcessing((JSONObject) value, removeFields, fieldMappings, stringProcessors, fieldPath);
            } else if (value instanceof JSONArray) {
                value = cleanJsonArrayWithStringProcessing((JSONArray) value, removeFields, fieldMappings, stringProcessors, fieldPath);
            }

            result.put(newKey, value);
        }

        return result;
    }

    /**
     * 清洗JSONObject（支持嵌套字段打平和字符串字段加工）
     */
    private static JSONObject cleanJsonObjectWithFlattenAndStringProcessing(JSONObject jsonObject, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings, Map<String, StringProcessor> stringProcessors, String currentPath) {
        JSONObject result = new JSONObject();
        Map<String, Object> flattenedFields = new HashMap<>();

        for (Map.Entry<String, Object> entry : jsonObject.entrySet()) {
            String key = entry.getKey();
            Object value = entry.getValue();

            // 构建当前字段的完整路径
            String fieldPath = currentPath.isEmpty() ? key : currentPath + "." + key;

            // 检查是否需要删除该字段
            if (shouldRemoveField(fieldPath, removeFields)) {
                continue;
            }

            // 检查是否需要打平该字段
            if (flattenMappings != null && flattenMappings.containsKey(fieldPath)) {
                String flattenedKey = flattenMappings.get(fieldPath);
                // 处理字符串字段加工
                if (stringProcessors != null && value instanceof String) {
                    StringProcessor processor = getStringProcessor(fieldPath, stringProcessors);
                    if (processor != null) {
                        value = processor.process((String) value);
                    }
                }
                flattenedFields.put(flattenedKey, value);
                continue;
            }

            // 获取新的字段名
            String newKey = getNewFieldName(key, fieldPath, fieldMappings);

            // 处理字符串字段加工
            if (stringProcessors != null && value instanceof String) {
                StringProcessor processor = getStringProcessor(fieldPath, stringProcessors);
                if (processor != null) {
                    value = processor.process((String) value);
                }
            }

            // 递归处理嵌套对象
            if (value instanceof JSONObject) {
                value = cleanJsonObjectWithFlattenAndStringProcessing((JSONObject) value, removeFields, fieldMappings, flattenMappings, stringProcessors, fieldPath);
            } else if (value instanceof JSONArray) {
                value = cleanJsonArrayWithFlattenAndStringProcessing((JSONArray) value, removeFields, fieldMappings, flattenMappings, stringProcessors, fieldPath);
            }

            result.put(newKey, value);
        }

        // 添加打平的字段到结果中
        result.putAll(flattenedFields);

        return result;
    }

    /**
     * 清洗JSONArray（支持字符串字段加工）
     */
    private static JSONArray cleanJsonArrayWithStringProcessing(JSONArray jsonArray, List<String> removeFields, Map<String, String> fieldMappings, Map<String, StringProcessor> stringProcessors, String currentPath) {
        JSONArray result = new JSONArray();

        for (int i = 0; i < jsonArray.size(); i++) {
            Object item = jsonArray.get(i);
            Object cleanedItem;

            if (item instanceof JSONObject) {
                cleanedItem = cleanJsonObjectWithStringProcessing((JSONObject) item, removeFields, fieldMappings, stringProcessors, currentPath);
            } else if (item instanceof JSONArray) {
                cleanedItem = cleanJsonArrayWithStringProcessing((JSONArray) item, removeFields, fieldMappings, stringProcessors, currentPath);
            } else {
                cleanedItem = item;
            }

            result.add(cleanedItem);
        }

        return result;
    }

    /**
     * 清洗JSONArray（支持嵌套字段打平和字符串字段加工）
     */
    private static JSONArray cleanJsonArrayWithFlattenAndStringProcessing(JSONArray jsonArray, List<String> removeFields, Map<String, String> fieldMappings, Map<String, String> flattenMappings, Map<String, StringProcessor> stringProcessors, String currentPath) {
        JSONArray result = new JSONArray();

        for (int i = 0; i < jsonArray.size(); i++) {
            Object item = jsonArray.get(i);
            Object cleanedItem;

            if (item instanceof JSONObject) {
                cleanedItem = cleanJsonObjectWithFlattenAndStringProcessing((JSONObject) item, removeFields, fieldMappings, flattenMappings, stringProcessors, currentPath);
            } else if (item instanceof JSONArray) {
                cleanedItem = cleanJsonArrayWithFlattenAndStringProcessing((JSONArray) item, removeFields, fieldMappings, flattenMappings, stringProcessors, currentPath);
            } else {
                cleanedItem = item;
            }

            result.add(cleanedItem);
        }

        return result;
    }

    /**
     * 字符串处理器接口
     */
    public interface StringProcessor {
        /**
         * 处理字符串值
         *
         * @param value 原始字符串值
         * @return 处理后的值
         */
        Object process(String value);
    }

    /**
     * 百分比字符串处理器
     * 将百分比字符串（如"90%"）转换为整数（90）
     */
    public static class PercentageProcessor implements StringProcessor {
        @Override
        public Object process(String value) {
            if (value == null || value.trim().isEmpty()) {
                return value;
            }

            String trimmedValue = value.trim();
            if (trimmedValue.endsWith("%")) {
                try {
                    String numberStr = trimmedValue.substring(0, trimmedValue.length() - 1);
                    return Integer.parseInt(numberStr);
                } catch (NumberFormatException e) {
                    log.warn("无法解析百分比字符串: {}", value);
                    return value;
                }
            }
            return value;
        }
    }

    /**
     * 浮点数字符串处理器
     * 将浮点数字符串（如"90.5"）转换为整数（90）
     */
    public static class FloatToIntProcessor implements StringProcessor {
        @Override
        public Object process(String value) {
            if (value == null || value.trim().isEmpty()) {
                return value;
            }

            try {
                double doubleValue = Double.parseDouble(value.trim());
                return (int) doubleValue;
            } catch (NumberFormatException e) {
                log.warn("无法解析浮点数字符串: {}", value);
                return value;
            }
        }
    }
}
