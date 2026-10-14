package com.ytell.zhiyuan.common.util;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 选科要求解析（Java 侧唯一口径，2026-10-14 选科适配 P0 修复）。
 *
 * <p>此前三处解析器各写各的：{@code MajorProfileManager}（专业画像 selectLimit）、
 * {@code VolunteerFilterChain}（候选池选科过滤）、{@code CandidateFitExplainService}
 * （适配性解释）。共同缺口：</p>
 * <ul>
 *   <li>"化或生"这类<b>或表达式</b>解析成空 → selectLimit 恒空 → 校验恒"满足"（假阳性，
 *       全模式）；或整体当单一科目 → 整条专业被误杀；</li>
 *   <li>不认识"技/技术"（07，浙江特有）；</li>
 *   <li>组合码形态（两位一组，如 {@code 010205}）完全解析不出来。</li>
 * </ul>
 *
 * <p>统一为 <b>「外层或、内层与」</b>结构（{@code List<List<String>>}）：
 * 外层任一组合满足即可；内层组合里的科目必须全部具备。-1 解析不出时返回<b>空列表</b>，
 * 调用方必须按"没有可核对的约束"处理（不得当成"不满足"）。</p>
 *
 * <p>教材编码与 {@code ScoreCatalogService.ELECTIVE_SUBJECTS}/上游选科策略同一套：
 * 01 物理、02 历史、03 政治、04 地理、05 化学、06 生物、07 技术。</p>
 */
public final class SubjectRequirementParser {

    /** 选考科目编码表（码, 全称）。 */
    private static final String[][] ELECTIVE_SUBJECTS = {
            {"01", "物理"}, {"02", "历史"}, {"03", "政治"}, {"04", "地理"},
            {"05", "化学"}, {"06", "生物"}, {"07", "技术"}};

    private static final Map<String, String> CODE_TO_NAME;
    private static final Map<String, String> TOKEN_TO_NAME;

    static {
        Map<String, String> codeToName = new LinkedHashMap<String, String>();
        Map<String, String> tokenToName = new LinkedHashMap<String, String>();
        for (String[] item : ELECTIVE_SUBJECTS) {
            codeToName.put(item[0], item[1]);
            tokenToName.put(item[1], item[1]);
        }
        // 单字缩写（与历史口径一致；补上此前缺失的"技"→技术）。
        tokenToName.put("物", "物理");
        tokenToName.put("化", "化学");
        tokenToName.put("生", "生物");
        tokenToName.put("政", "政治");
        tokenToName.put("史", "历史");
        tokenToName.put("地", "地理");
        tokenToName.put("技", "技术");
        CODE_TO_NAME = Collections.unmodifiableMap(codeToName);
        TOKEN_TO_NAME = Collections.unmodifiableMap(tokenToName);
    }

    private SubjectRequirementParser() {
    }

    /** 两位编码 → 全称；未知码返回 null。 */
    public static String subjectNameForCode(String code) {
        return code == null ? null : CODE_TO_NAME.get(code.trim());
    }

    /** 单科 token（单字缩写或全称）→ 全称；不是单科科目返回 null。 */
    public static String toSubjectName(String token) {
        if (token == null) {
            return null;
        }
        return TOKEN_TO_NAME.get(token.trim());
    }

    /**
     * 组合码串 → 或/与结构。语义：**两位一组**，逗号（半/全角）分隔的每一段是一组
     * 「该组科目全部具备」的组合，段与段之间是「任一组合满足即可」。
     * 例：{@code "010205,010305"} → {@code [[物理,历史,化学],[物理,政治,化学]]}。
     *
     * <p>段长非偶、出现未知码 → 返回空列表（整体 fail-open，不半猜）。</p>
     */
    public static List<List<String>> parseCombinationCodes(String codes) {
        List<List<String>> options = new ArrayList<List<String>>();
        String info = codes == null ? "" : codes.trim();
        if (info.isEmpty()) {
            return options;
        }
        for (String rawToken : info.split("[,，]")) {
            String token = rawToken.trim();
            if (token.isEmpty()) {
                continue;
            }
            if (token.length() % 2 != 0) {
                return new ArrayList<List<String>>();
            }
            List<String> combination = new ArrayList<String>();
            for (int i = 0; i < token.length(); i += 2) {
                String name = CODE_TO_NAME.get(token.substring(i, i + 2));
                if (name == null) {
                    return new ArrayList<List<String>>();
                }
                if (!combination.contains(name)) {
                    combination.add(name);
                }
            }
            options.add(combination);
        }
        return options;
    }

    /**
     * 自然语言选科要求 → 或/与结构。
     *
     * <p>支持（按真实数据形态）：{@code "不限"}、单科（{@code 物/化/…/技} 或全称）、
     * {@code "物和化"}（都要）、{@code "化或生"}（任一）、{@code "物和(化或生)"}（与+或嵌套）、
     * {@code "物理或化学"}（全称写法）。</p>
     *
     * <p>空串 / 含"不限" / 解析不出（未知 token、括号残缺）→ 返回空列表。</p>
     */
    public static List<List<String>> parseOptions(String requirement) {
        List<List<String>> empty = new ArrayList<List<String>>();
        String info = requirement == null ? "" : requirement.trim();
        if (info.isEmpty() || info.contains("不限")) {
            return empty;
        }
        info = info.replace('（', '(').replace('）', ')');

        // 括号段先抽出来做占位符：段内 "或" = 备选；否则必须是单个科目 token。
        Map<String, String[]> placeholders = new LinkedHashMap<String, String[]>();
        StringBuilder masked = new StringBuilder();
        int index = 0;
        while (index < info.length()) {
            char ch = info.charAt(index);
            if (ch == '(') {
                int close = info.indexOf(')', index);
                if (close < 0) {
                    return empty;
                }
                String inner = info.substring(index + 1, close);
                List<String> alternatives = new ArrayList<String>();
                String[] parts = inner.contains("或") ? inner.split("或") : new String[]{inner};
                for (String part : parts) {
                    String name = toSubjectName(part);
                    if (name == null) {
                        return empty;
                    }
                    if (!alternatives.contains(name)) {
                        alternatives.add(name);
                    }
                }
                if (alternatives.isEmpty()) {
                    return empty;
                }
                String key = "\u0000" + placeholders.size();
                placeholders.put(key, alternatives.toArray(new String[0]));
                // 占位符两侧补"和"（隐式与）："物(化或生)" 与 "物和(化或生)" 同解。
                if (masked.length() > 0 && masked.charAt(masked.length() - 1) != '和') {
                    masked.append('和');
                }
                masked.append(key);
                masked.append('和');
                index = close + 1;
            } else if (ch == ')') {
                return empty;
            } else {
                masked.append(ch);
                index++;
            }
        }

        // 顶层 "和" = 与（每个与项内部 "或" = 备选）。
        // 注意：占位符 key 以 \u0000 开头，而 String.trim() 会吃掉 \u0000（chars<=空格），
        // 所以占位符查找必须用未 trim 的原段（历史 bug：物和(化或生)整体解析成空）。
        List<String[]> andGroups = new ArrayList<String[]>();
        for (String rawTerm : masked.toString().split("和")) {
            String[] alternatives = placeholders.get(rawTerm);
            String term = rawTerm.trim();
            if (term.isEmpty() && alternatives == null) {
                continue;
            }
            if (alternatives == null && term.contains("或")) {
                List<String> names = new ArrayList<String>();
                for (String part : term.split("或")) {
                    String name = toSubjectName(part);
                    if (name == null) {
                        return empty;
                    }
                    if (!names.contains(name)) {
                        names.add(name);
                    }
                }
                alternatives = names.toArray(new String[0]);
            }
            if (alternatives == null) {
                String name = toSubjectName(term);
                if (name == null) {
                    return empty;
                }
                alternatives = new String[]{name};
            }
            andGroups.add(alternatives);
        }
        if (andGroups.isEmpty()) {
            return empty;
        }

        // 笛卡尔积：外层"="，内层="与"。
        List<List<String>> acc = new ArrayList<List<String>>();
        acc.add(new ArrayList<String>());
        for (String[] group : andGroups) {
            List<List<String>> next = new ArrayList<List<String>>();
            for (List<String> prefix : acc) {
                for (String alternative : group) {
                    List<String> combination = new ArrayList<String>(prefix);
                    if (!combination.contains(alternative)) {
                        combination.add(alternative);
                    }
                    if (!next.contains(combination)) {
                        next.add(combination);
                    }
                }
            }
            acc = next;
        }
        return acc;
    }
}
