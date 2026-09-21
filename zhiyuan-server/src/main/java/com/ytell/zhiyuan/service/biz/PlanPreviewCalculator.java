package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.serializer.SerializerFeature;
import com.ytell.zhiyuan.model.dto.planning.FrozenPlanPayloadDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * 预览的**纯计算**部分：只在 DTO 副本上演算，不碰数据库。
 *
 * <p>之所以独立成类：`PlanningStateService` 已经 11762 行，把预览塞进去
 * 只会让"哪条路径会写库"更难回答。这里的方法**不可能**写库——它们没有
 * 任何 mapper 依赖，签名上也看不出来能拿到持久化入口。
 *
 * <p>摘要按**分项**计算，理由见 {@link FrozenPlanPayloadDTO}：
 * selection 与 ordering 是两次独立求解，合并摘要会把"哪一项变了"藏起来。
 */
final class PlanPreviewCalculator {

    private PlanPreviewCalculator() {
    }

    /**
     * 深复制：在副本上演算，原对象一个字段都不动。
     *
     * <p>这是"预览无副作用"的技术前提——只要有一个字段是引用传递的，
     * 演算就会顺着引用改到真实状态上，而那正是"预览把正式表改了"的成因。
     */
    static PlanningStateDTO deepCopy(PlanningStateDTO source) {
        if (source == null) {
            return null;
        }
        return JSON.parseObject(JSON.toJSONString(source), PlanningStateDTO.class);
    }

    static String digest(Object value) {
        String canonical = JSON.toJSONString(value,
                SerializerFeature.MapSortField, SerializerFeature.SortField);
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] bytes = md.digest(canonical.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(bytes.length * 2);
            for (byte item : bytes) {
                builder.append(Character.forDigit((item >> 4) & 0xF, 16));
                builder.append(Character.forDigit(item & 0xF, 16));
            }
            return builder.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 unavailable", ex);
        }
    }

    /**
     * 载荷摘要：由**分项摘要 + 求解器版本**合成。
     *
     * <p>刻意不把两份 trace 算进去：trace 是解释，不是产物。
     * 把解释算进摘要会让"内容没变但 trace 变长"被判成载荷变了。
     */
    static String payloadDigest(FrozenPlanPayloadDTO frozen) {
        if (frozen == null) {
            return null;
        }
        return digest(new String[] {
                digest(frozen.getWorkingPlan()),
                digest(frozen.getOrderedPlan()),
                frozen.getObjectiveDigest(),
                frozen.getCandidateDigest(),
                frozen.getProfileDigest(),
                frozen.getSolverVersion(),
        });
    }
}
