package com.ytell.zhiyuan.common.base;

import lombok.Data;

import java.io.Serializable;

@Data
public class BaseResponse<T> implements Serializable {

    private T data;
    private int code;
    private String msg;

    private BaseResponse() {

    }

    public static <T> BaseResponse<T> error(int code, String msg) {
        BaseResponse response = new BaseResponse();
        response.setCode(code);
        response.setMsg(msg);
        return response;
    }

    public static <T> BaseResponse<T> success(T data) {
        BaseResponse response = new BaseResponse();
        response.setCode(0);
        response.setMsg("success");
        response.setData(data);
        return response;
    }

    public static <T> BaseResponse<T> success() {
        BaseResponse response = new BaseResponse();
        response.setCode(0);
        response.setMsg("success");
        return response;
    }

}
