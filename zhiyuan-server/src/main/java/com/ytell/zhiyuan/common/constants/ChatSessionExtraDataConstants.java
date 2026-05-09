package com.ytell.zhiyuan.common.constants;

/**
 * 聊天会话额外数据常量类
 * 统一管理ChatSessionExtraData中使用的dataKey常量
 *
 * @author system
 */
public class ChatSessionExtraDataConstants {

    /**
     * 用户成绩详情数据key
     */
    public static final String USER_SCORE_KEY = "userScoreDetail";

    /**
     * 用户意愿数据-（基于会话中表达的提取的）key
     */
    public static final String USER_PROFILE_KEY = "userprofile";

    /**
     * 用户初始意愿-（基于优势学科推导的）key
     */
    public static final String USER_INIT_PROFILE_KEY = "userInitProfile";

    /**
     * 用户会话情况数据key
     */
    public static final String USER_SESSION_SITUATION_KEY = "sessionSituation";

    /**
     * 规划状态聚合数据key
     */
    public static final String PLANNING_STATE_KEY = "planningState";

    /**
     * 对话中暂存的方案编辑意向key
     */
    public static final String PLAN_EDIT_CACHE_KEY = "planEditCache";

    /**
     * 私有构造函数，防止实例化
     */
    private ChatSessionExtraDataConstants() {
        throw new UnsupportedOperationException("常量类不能被实例化");
    }
}
