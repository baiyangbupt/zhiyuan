package com.ytell.zhiyuan.common.util;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.DataType;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

public class ChatSessionExtraDataConverter {


    public static Object convertToObj(ChatSessionExtraData data) {

        DateTimeFormatter dateFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
        DateTimeFormatter dateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        DateTimeFormatter timeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss");
        DataType dataType = data.getDataType();
        String value = data.getDataValue();

        Object convertedValue;
        switch (dataType) {
            case STRING:
                convertedValue = value;
                break;
            case NUMBER:
                convertedValue = Integer.parseInt(value);
                break;
            case DATE:
                convertedValue = LocalDate.parse(value, dateFormatter);
                break;
            case DATETIME:
                convertedValue = LocalDateTime.parse(value, dateTimeFormatter);
                break;
            case TIME:
                convertedValue = LocalTime.parse(value, timeFormatter);
                break;
            case JSON_OBJECT:
                convertedValue = JSONObject.parseObject(value);
                break;
            case JSON_ARRAY:
                convertedValue = JSONArray.parseArray(value);
                break;
            default:
                throw new IllegalArgumentException("Unsupported data type: " + dataType);
        }
        return convertedValue;
    }

    public static Map<String, Object> convertToMap(List<ChatSessionExtraData> extraDataList) {
        Map<String, Object> result = Maps.newHashMap();
        for (ChatSessionExtraData data : extraDataList) {
            String key = data.getDataKey();
            result.put(key, convertToObj(data));
        }
        return result;
    }

    public static String convertValue(DataType dataType, Object dataValue) {
        String convertedValue;
        switch (dataType) {
            case STRING:
            case NUMBER:
            case DATE:
            case DATETIME:
            case TIME:
                convertedValue = String.valueOf(dataValue);
                break;
            case JSON_OBJECT:
                convertedValue = JSONObject.toJSONString(dataValue);
                break;
            case JSON_ARRAY:
                convertedValue = JSONArray.toJSONString(dataValue);
                break;
            default:
                throw new IllegalArgumentException("Unsupported data type: " + dataType);
        }
        return convertedValue;
    }

}