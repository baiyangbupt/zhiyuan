package com.ytell.zhiyuan.model.dto;

import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import lombok.Data;

/**
 * 空会话（draft）**同会话补录成绩**的响应契约。
 *
 * <p>字段是给浏览器用的最小状态集：</p>
 * <ul>
 *   <li>{@code success}：成绩详情已落库（本次请求的整体结果；失败走既有错误码）；</li>
 *   <li>{@code planningVersion}：补录后的规划状态版本（已 +1）。前端拿它判断
 *       "workspace 状态已经变过"；</li>
 *   <li>{@code staleFlags}：候选池/推荐/方案/审查哪些已失效，前端可直接打在卡片上；</li>
 *   <li>{@code requiresWorkspaceReload}：**恒为 true**——版本已变、候选池成绩上下文已刷新，
 *       前端应当重新拉 workspace-state（而不是继续用补录前的缓存）；</li>
 *   <li>{@code volunteerSourceDataSynced} / {@code volunteerSourceDataFetchedAt}：
 *       志愿全量数据是否已重新拉取并落盘（空会话建会话时故意没拉，这里补上）。</li>
 * </ul>
 */
@Data
public class UpdateScoreDetailRes {

    private Boolean success;

    private Long chatSessionId;

    private Integer planningVersion;

    private StaleFlagsDTO staleFlags;

    private Boolean requiresWorkspaceReload;

    private Boolean volunteerSourceDataSynced;

    /** 志愿源数据拉取时间（ISO-8601，来自 VolunteerSourceDataSnapshot#getFetchedAt）。 */
    private String volunteerSourceDataFetchedAt;
}
