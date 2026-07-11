package com.ytell.zhiyuan.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import org.junit.jupiter.api.Test;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class FlowConfigResourceTest {

    @Test
    void tuitionRangeShouldSupportTwoHundredThousandWithOneHundredThousandDefault() throws Exception {
        JSONObject flowConfig = JSON.parseObject(readResource("bizdata/gaokao_volunteer_flow_config.json"));
        JSONObject tuitionRange = findField(flowConfig, "tuitionRange");

        assertNotNull(tuitionRange);
        assertEquals(Integer.valueOf(0), tuitionRange.getInteger("min"));
        assertEquals(Integer.valueOf(200000), tuitionRange.getInteger("max"));
        assertEquals(Integer.valueOf(1000), tuitionRange.getInteger("step"));

        JSONObject defaultValue = tuitionRange.getJSONObject("defaultValue");
        assertNotNull(defaultValue);
        assertEquals(Integer.valueOf(0), defaultValue.getInteger("minValue"));
        assertEquals(Integer.valueOf(100000), defaultValue.getInteger("maxValue"));
    }

    private static String readResource(String resourcePath) throws Exception {
        InputStream inputStream = FlowConfigResourceTest.class.getClassLoader().getResourceAsStream(resourcePath);
        assertNotNull(inputStream, "missing resource: " + resourcePath);
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8))) {
            StringBuilder content = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                content.append(line);
            }
            return content.toString();
        }
    }

    private static JSONObject findField(Object node, String fieldId) {
        if (node instanceof JSONObject) {
            JSONObject jsonObject = (JSONObject) node;
            if (fieldId.equals(jsonObject.getString("fieldId"))) {
                return jsonObject;
            }
            for (Map.Entry<String, Object> entry : jsonObject.entrySet()) {
                JSONObject found = findField(entry.getValue(), fieldId);
                if (found != null) {
                    return found;
                }
            }
        } else if (node instanceof JSONArray) {
            JSONArray jsonArray = (JSONArray) node;
            for (Object item : jsonArray) {
                JSONObject found = findField(item, fieldId);
                if (found != null) {
                    return found;
                }
            }
        }
        return null;
    }
}
