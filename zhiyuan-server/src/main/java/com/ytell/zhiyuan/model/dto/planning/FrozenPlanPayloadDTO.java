package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 冻结的方案载荷：一次预览的结果，写进 Pending 后**不再重算**。
 *
 * <p>为什么必须冻结：用户看到的 diff 与他确认后落库的内容必须是**同一份东西**。
 * 确认时重新跑一遍推荐，即使输入没变，只要求解器有任何一个非确定性环节
 * （或候选在此期间变过），落库的就可能不是他看到的那份——而他点的是"确认"，
 * 不是"再随机一次"。
 *
 * <p>摘要是**分项**的，不是合并成一个大摘要：
 * selection 与 ordering 是两次独立求解，输入不同、产物不同。
 * 合成一个摘要之后，"到底是目标变了还是候选变了"就查不出来了。
 */
@Data
public class FrozenPlanPayloadDTO {
    private DraftPlanStateDTO workingPlan;
    private OrderedPlanStateDTO orderedPlan;

    /** 各自输入摘要，分开存。 */
    private String objectiveDigest;
    private String candidateDigest;
    private String profileDigest;

    /** 求解器版本：换了求解器实现，同一份输入的产物也可能不同。 */
    private String solverVersion;

    /** 载荷自身的摘要：写入与读取时复核，防止被改过。 */
    private String payloadDigest;

    /** selection 的求解 trace，只作解释，**不**参与载荷摘要合并。 */
    private String selectionTrace;

    /** ordering 的求解 trace，同上，与 selection 分开。 */
    private String orderingTrace;
}
