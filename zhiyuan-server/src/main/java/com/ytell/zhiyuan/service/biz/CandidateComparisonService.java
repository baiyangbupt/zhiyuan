package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateComparisonDTO;
import com.ytell.zhiyuan.model.dto.planning.ComparisonCellDTO;
import com.ytell.zhiyuan.model.dto.planning.ComparisonEntityDTO;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * 同口径比较矩阵。
 *
 * <p>比较最容易出的不是"算错了"，而是**把不可比的数放在一起比**：
 * 2024 年的位次减 2026 年的位次、学校口径的率减专业组的率、
 * 缺失值补零之后"看起来更低"。这三种都会得出一个方向相反的建议。
 *
 * <p>所以这一层的核心不是算术，而是**可比性判定**：
 * <ol>
 *   <li>数值维度只有在口径完全一致时才计算，否则整列标 `unavailable`；</li>
 *   <li>缺失保持 `null` 并注明原因，**不补零**；</li>
 *   <li>概率与匹配分是两个不同字段，不互相替代。</li>
 * </ol>
 */
@Service
public class CandidateComparisonService {

    /** 比较的实体数上限。再多用户也读不过来，而且表格会溢出。 */
    public static final int MIN_ENTITIES = 2;
    public static final int MAX_ENTITIES = 5;

    /** 允许比较的维度白名单。不在表里的维度一律拒绝，避免把任意字段都搬上来。 */
    public static final List<String> DIMENSIONS = Collections.unmodifiableList(Arrays.asList(
            "admissionRatio", "finalScore", "planNum", "tuitionPerYear", "schoolEnrollRatio", "cityName"));

    /** 需要口径一致才有意义的维度。名称类维度不受口径影响。 */
    private static final Set<String> NUMERIC_DIMENSIONS = new LinkedHashSet<String>(Arrays.asList(
            "admissionRatio", "finalScore", "planNum", "tuitionPerYear", "schoolEnrollRatio"));

    /** 口径身份：五个字段全等才算同口径。 */
    private static final String[] SCOPE_FIELDS = {
            "admissionYear", "areaId", "batch", "admissionMode", "rateUnit"
    };

    public CandidateComparisonDTO compare(List<ComparisonEntityDTO> entities, List<String> dimensions) {
        if (entities == null || entities.size() < MIN_ENTITIES || entities.size() > MAX_ENTITIES) {
            throw new BusinessException(400, "comparison_entity_count_invalid");
        }
        List<String> requested = resolveDimensions(dimensions);

        boolean scopeMatches = sameScope(entities);

        CandidateComparisonDTO result = new CandidateComparisonDTO();
        result.setEntities(entities);
        result.setDimensions(new ArrayList<String>(requested));
        List<ComparisonCellDTO> cells = new ArrayList<ComparisonCellDTO>();
        List<String> unavailableDimensions = new ArrayList<String>();

        for (String dimension : requested) {
            if (NUMERIC_DIMENSIONS.contains(dimension) && !scopeMatches) {
                // 口径不一致时**整列不可比**，而不是"逐格标一下"：
                // 一张表里有一列能比一列不能比，读者会以为整张表都能比。
                unavailableDimensions.add(dimension);
                for (ComparisonEntityDTO entity : entities) {
                    cells.add(unavailableCell(entity, dimension, "scope_mismatch"));
                }
                continue;
            }
            for (ComparisonEntityDTO entity : entities) {
                cells.add(buildCell(entity, dimension));
            }
        }

        result.setCells(cells);
        result.setUnavailableDimensions(unavailableDimensions);
        List<String> limitations = new ArrayList<String>();
        if (!scopeMatches) {
            limitations.add("comparison_scope_mismatch");
        }
        result.setLimitations(limitations);
        return result;
    }

    /**
     * 维度白名单判定，返回本次生效的维度列表。**两条入口共用同一份判据**：
     * 值由调用方传的 {@link #compare} 与被载入的候选行比较
     * （{@link CandidateCompareService}）——维度名与白名单只能有一处定义，
     * 否则"哪些列能比"会因入口不同而不同。
     */
    public static List<String> resolveDimensions(List<String> requested) {
        List<String> dimensions = requested == null || requested.isEmpty()
                ? new ArrayList<String>(DIMENSIONS) : new ArrayList<String>(requested);
        for (String dimension : dimensions) {
            if (!DIMENSIONS.contains(dimension)) {
                throw new BusinessException(400, "comparison_dimension_unsupported");
            }
        }
        return dimensions;
    }

    /**
     * 口径是否一致。**缺失也算不一致**——"不知道口径是否相同"不等于"相同"。
     */
    public static boolean comparable(ComparisonEntityDTO left, ComparisonEntityDTO right) {
        if (left == null || right == null) {
            return false;
        }
        for (String field : SCOPE_FIELDS) {
            if (readScope(left, field) == null || readScope(right, field) == null) {
                return false;
            }
            if (!Objects.equals(readScope(left, field), readScope(right, field))) {
                return false;
            }
        }
        return true;
    }

    private static boolean sameScope(List<ComparisonEntityDTO> entities) {
        ComparisonEntityDTO first = entities.get(0);
        for (int index = 1; index < entities.size(); index++) {
            if (!comparable(first, entities.get(index))) {
                return false;
            }
        }
        return true;
    }

    private static Object readScope(ComparisonEntityDTO entity, String field) {
        switch (field) {
            case "admissionYear":
                return entity.getAdmissionYear();
            case "areaId":
                return blankToNull(entity.getAreaId());
            case "batch":
                return blankToNull(entity.getBatch());
            case "admissionMode":
                return blankToNull(entity.getAdmissionMode());
            case "rateUnit":
                return blankToNull(entity.getRateUnit());
            default:
                return null;
        }
    }

    private ComparisonCellDTO buildCell(ComparisonEntityDTO entity, String dimension) {
        ComparisonCellDTO cell = new ComparisonCellDTO();
        cell.setEntityId(entity.getEntityId());
        cell.setDimension(dimension);
        // 来源前缀随实体走：值从候选池行载入时写 `candidatePool.*`，而不是继续自称 entity。
        String source = sourcePrefix(entity);
        switch (dimension) {
            case "admissionRatio":
                cell.setValue(entity.getAdmissionRatio());
                cell.setSource(source + ".admissionRatio");
                cell.setUnit(entity.getRateUnit());
                if (entity.getAdmissionRatio() == null) {
                    cell.setUnavailableReason("admission_ratio_missing");
                }
                break;
            case "schoolEnrollRatio":
                cell.setValue(entity.getSchoolEnrollRatio());
                cell.setSource(source + ".schoolEnrollRatio");
                cell.setUnit(entity.getRateUnit());
                // 学校率与单元率是两个口径，字段名不同、来源不同，不能互相顶替。
                if (entity.getSchoolEnrollRatio() == null) {
                    cell.setUnavailableReason("school_enroll_ratio_missing");
                }
                break;
            case "finalScore":
                cell.setValue(entity.getFinalScore());
                cell.setSource(source + ".finalScore");
                cell.setUnit("score");
                if (entity.getFinalScore() == null) {
                    cell.setUnavailableReason("final_score_missing");
                }
                break;
            case "planNum":
                cell.setValue(entity.getPlanNum());
                cell.setSource(source + ".planNum");
                cell.setUnit("person");
                if (entity.getPlanNum() == null) {
                    cell.setUnavailableReason("plan_num_missing");
                }
                break;
            case "tuitionPerYear":
                cell.setValue(entity.getTuitionPerYear());
                cell.setSource(source + ".tuitionPerYear");
                cell.setUnit("cny_per_year");
                if (entity.getTuitionPerYear() == null) {
                    cell.setUnavailableReason("tuition_missing");
                }
                break;
            case "cityName":
                // 名称类维度不受口径影响：城市名不随年份变化。
                cell.setValue(entity.getCityName());
                cell.setSource(source + ".cityName");
                if (blankToNull(entity.getCityName()) == null) {
                    cell.setUnavailableReason("city_missing");
                }
                break;
            default:
                cell.setUnavailableReason("dimension_unsupported");
        }
        // 缺失就是缺失：值是 null，不能补零——补零之后"没有数据"看起来像"更低"。
        return cell;
    }

    /** 单元的 source 前缀。缺省 `entity`：调用方自带的值，不改历史口径。 */
    private static String sourcePrefix(ComparisonEntityDTO entity) {
        String source = blankToNull(entity.getValueSource());
        return source == null ? "entity" : source;
    }

    private ComparisonCellDTO unavailableCell(ComparisonEntityDTO entity, String dimension, String reason) {
        ComparisonCellDTO cell = new ComparisonCellDTO();
        cell.setEntityId(entity.getEntityId());
        cell.setDimension(dimension);
        cell.setValue(null);
        cell.setUnavailableReason(reason);
        return cell;
    }

    private static String blankToNull(String value) {
        return value == null || value.trim().isEmpty() ? null : value.trim();
    }
}
