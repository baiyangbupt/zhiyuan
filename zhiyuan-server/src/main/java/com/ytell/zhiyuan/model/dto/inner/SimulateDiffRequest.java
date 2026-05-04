package com.ytell.zhiyuan.model.dto.inner;

import com.ytell.zhiyuan.model.dto.UserProfileData;
import lombok.Data;

/**
 * 模拟对比请求 —— 携带拟修改的画像数据，后端在内存中临时合并后重新推荐，
 * 与缓存的当前方案做 diff，返回影响摘要。
 */
@Data
public class SimulateDiffRequest {

    /**
     * 拟修改后的完整画像（正向 + 负向），
     * 即 agent 端已经把本次 edit 的 intent 合并到当前画像上之后的结果。
     * 后端直接用此画像替换原始画像、走 mergeUserProfile → 推荐流水线。
     */
    private UserProfileData proposedProfile;
}
