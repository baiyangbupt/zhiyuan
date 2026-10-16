package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * planningState 行里指向候选池大文档（{@code planningCandidatePool} 行）的引用
 * （池状态瘦身·切片1，2026-10-16 review §五-54）。
 *
 * <ul>
 *   <li>存在即"本 planningState 是拆分态"：items 不在本行，在池行里（读闸口回填）；</li>
 *   <li>len/md5 = 池行 data_value 的 UTF-8 字节长度与 MD5 摘要（与 MySQL {@code LENGTH()}/{@code MD5()}
 *       同口径，复用 ①② {@code a344f4c} 的字节级实现）；</li>
 *   <li>md5 让"小行 CAS 赢"蕴含"池行自读到的那份起没被并发改过"（池一变 md5 必变，小行必变，
 *       小行 CAS 即失败/重试）——写侧"先 CAS 池行、再写小行"的原子性判据。</li>
 * </ul>
 *
 * <p>本字段不参与常规 fastjson 序列化（行内 JSON 由 {@code PlanningStateService} 手工带上），
 * 也不进 /session/state 对外 JSON（Jackson @JsonIgnore）——对外形状不变。</p>
 */
@Data
public class CandidatePoolRefDTO {
    /** 池行 data_value 的 UTF-8 字节长度（MySQL LENGTH 口径）。 */
    private Long len;
    /** 池行 data_value 的 MD5 小写十六进制（MySQL MD5 口径）。 */
    private String md5;
}
