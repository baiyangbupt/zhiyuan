package com.ytell.zhiyuan.model.dto.gaotu.res;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;

/**
 * 院校资讯（招生章程/招生简章）的列表与详情。
 *
 * <p>同一个类承载两种形状，因为它们本来就是同一条记录：列表只回标题与时间，
 * 详情才带 {@code content}。拆成两个类会让"列表里的第 3 条就是详情里那条"
 * 这件事变成靠两个 DTO 的字段对齐来保证。</p>
 *
 * <p>⚠️ 与 {@code getSchoolRule}（录取规则**摘要**，没规则时回占位文案、响应无标志位）
 * **不是一回事**：这条是学校发布的**招生章程全文**，标题自带年份、有上下架标志。
 * 引用章程时用这条，不要用那条。</p>
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class SchoolNewsRes {

    private Long id;
    private Long schoolId;
    private String schoolName;
    private String title;
    private String content;
    private String typeName;
    private Boolean isPublish;
    private String displayTime;
    private String createTime;

    /** 分页信封（列表接口用）。 */
    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Page {
        private List<SchoolNewsRes> records;
        private Long total;
        private Long current;
        private Long size;
    }
}
