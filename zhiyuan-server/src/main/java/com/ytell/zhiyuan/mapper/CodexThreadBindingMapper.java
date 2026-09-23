package com.ytell.zhiyuan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ytell.zhiyuan.model.entity.biz.CodexThreadBindingEntity;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Date;

@Mapper
public interface CodexThreadBindingMapper extends BaseMapper<CodexThreadBindingEntity> {

    /**
     * 取该 (租户, 会话) 当前有效的绑定：未撤销、未过期，最近更新的一条。
     *
     * <p>用途是 Gateway 重启后找回 thread——那时进程内的 handle 已经没了，
     * 所以这条查询**不校验 handle**，只认内部调用方身份。</p>
     *
     * <p>按 {@code update_time} 倒序取第一条，是因为一个会话可能有过多个 thread
     * （上一个 rollout 丢了、resume 不通，于是重建）。同一 thread 重新注册时
     * 走的是更新既有行，所以"最近更新"恰是"现在活着的那一个"。
     * {@code id} 是次序兜底：同一秒内更新过的两条不能靠时间戳分先后。</p>
     */
    @Select("SELECT id, tenant_id, chat_session_id, user_id, thread_id, handle_hash, "
            + "allowed_capabilities, expires_at, revoked_at, create_time, update_time "
            + "FROM assistant_codex_thread_binding "
            + "WHERE tenant_id = #{tenantId} AND chat_session_id = #{chatSessionId} "
            + "AND revoked_at IS NULL AND expires_at > #{now} "
            + "ORDER BY update_time DESC, id DESC LIMIT 1")
    CodexThreadBindingEntity selectCurrent(@Param("tenantId") Long tenantId,
                                           @Param("chatSessionId") Long chatSessionId,
                                           @Param("now") Date now);
}
