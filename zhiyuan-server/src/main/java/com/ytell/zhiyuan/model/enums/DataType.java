package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

/**
 * 个性化数据的数据类型
 */
@AllArgsConstructor
@Getter
public enum DataType {
    STRING(0), NUMBER(1), DATE(2), DATETIME(3), TIME(4), JSON_OBJECT(5), JSON_ARRAY(6);

    @EnumValue
    private final Integer value;

    public static DataType valueOf(Integer value) {
        if (value == null) {
            return null;
        }
        for (DataType type : DataType.values()) {
            if (type.value == value) {
                return type;
            }
        }
        return null;
    }
}
