package com.ytell.zhiyuan.model.dto.gaotu.res;

import lombok.Data;

/**
 * 招生计划一行（上游 `PlanMajorDataResponse` 的镜像）。
 *
 * <p>`batch` 用 `Object` 而不是 String：上游是 `RemoteData&lt;String,String&gt;`
 * 包装，线上到底是"id+name 两个字段"还是"嵌套对象"**没有样本**。
 * 强类型等于替上游声明一个我没验证过的形状——那正是 P1a 栽过的跟头。
 */
@Data
public class PlanMajorDataRes {
    private Integer key;
    /** 计划代码：招生单元/专业在计划里的身份，与分数线里的 planMajorDataId 同源。 */
    private String majorPlanCode;
    private String majorSubtitle;
    private Object batch;
    /** 选科信息原文。 */
    private String selectInfo;
    private Integer planNum;
    /** 学制，上游是字符串（"4" / "4年" 未验证）。 */
    private String planDuration;
    /** 学费，上游是字符串。 */
    private String planMoney;
    private String majorId;
}
