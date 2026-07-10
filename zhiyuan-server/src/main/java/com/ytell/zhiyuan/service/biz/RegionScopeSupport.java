package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

final class RegionScopeSupport {

    private static final Map<String, String> AREA_ALIASES = buildAreaAliases();
    private static final Map<String, List<String>> AREA_PROVINCES = buildAreaProvinces();
    private static final Map<String, List<String>> AREA_CITIES = buildAreaCities();

    private RegionScopeSupport() {
    }

    static List<String> provincesForArea(String area) {
        return AREA_PROVINCES.get(normalizeAreaName(area));
    }

    static boolean matchesRegionScope(String scope, String provinceName, String cityName) {
        if (Strings.isNullOrEmpty(scope)) {
            return false;
        }
        String area = normalizeAreaName(scope);
        List<String> provinces = AREA_PROVINCES.get(area);
        if (provinces != null && provinces.stream().anyMatch(province -> regionNameEquals(province, provinceName))) {
            return true;
        }
        List<String> cities = AREA_CITIES.get(area);
        return cities != null && cities.stream().anyMatch(city -> regionNameEquals(city, cityName));
    }

    static String normalizeAreaName(String value) {
        String text = stripRegionSuffix(Strings.nullToEmpty(value).trim());
        String alias = AREA_ALIASES.get(text);
        return Strings.isNullOrEmpty(alias) ? text : alias;
    }

    private static boolean regionNameEquals(String left, String right) {
        String normalizedLeft = compactRegionName(stripRegionSuffix(left));
        String normalizedRight = compactRegionName(stripRegionSuffix(right));
        return !Strings.isNullOrEmpty(normalizedLeft) && normalizedLeft.equals(normalizedRight);
    }

    private static String compactRegionName(String value) {
        return Strings.nullToEmpty(value).trim().toLowerCase(Locale.ROOT).replaceAll("\\s+", "");
    }

    private static String stripRegionSuffix(String value) {
        String text = Strings.nullToEmpty(value).trim();
        for (String suffix : Arrays.asList("维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "特别行政区", "省", "市")) {
            if (text.endsWith(suffix)) {
                return text.substring(0, text.length() - suffix.length()).trim();
            }
        }
        return text;
    }

    private static Map<String, String> buildAreaAliases() {
        Map<String, String> map = new LinkedHashMap<String, String>();
        map.put("南方地区", "南方");
        map.put("南边", "南方");
        map.put("北方地区", "北方");
        map.put("北边", "北方");
        map.put("长三角地区", "长三角");
        map.put("江浙沪", "长三角");
        map.put("珠三角地区", "珠三角");
        map.put("华东地区", "华东");
        map.put("华北地区", "华北");
        map.put("华中地区", "华中");
        map.put("华南地区", "华南");
        map.put("东北地区", "东北");
        map.put("东三省", "东北");
        map.put("偏远", "偏远地区");
        map.put("边远地区", "偏远地区");
        map.put("西北地区", "西北");
        map.put("西南地区", "西南");
        map.put("东南地区", "东南");
        map.put("中南地区", "中南");
        return Collections.unmodifiableMap(map);
    }

    private static Map<String, List<String>> buildAreaProvinces() {
        Map<String, List<String>> map = new LinkedHashMap<String, List<String>>();
        map.put("南方", Arrays.asList(
                "浙江", "上海", "湖南", "湖北", "江西", "福建", "云南", "贵州",
                "四川", "重庆", "广东", "广西", "海南", "江苏", "安徽"));
        map.put("北方", Arrays.asList(
                "黑龙江", "吉林", "辽宁", "内蒙古", "新疆", "西藏", "青海", "甘肃",
                "宁夏", "陕西", "山西", "山东", "河北", "北京", "天津"));
        map.put("长三角", Arrays.asList("上海", "江苏", "浙江", "安徽"));
        map.put("华东", Arrays.asList("上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"));
        map.put("华北", Arrays.asList("北京", "天津", "河北", "山西", "内蒙古"));
        map.put("华中", Arrays.asList("河南", "湖北", "湖南"));
        map.put("华南", Arrays.asList("广东", "广西", "海南"));
        map.put("东北", Arrays.asList("辽宁", "吉林", "黑龙江"));
        map.put("西北", Arrays.asList("陕西", "甘肃", "青海", "宁夏", "新疆"));
        map.put("西南", Arrays.asList("重庆", "四川", "贵州", "云南", "西藏"));
        map.put("中南", Arrays.asList("河南", "湖北", "湖南", "广东", "广西", "海南"));
        map.put("东南", Arrays.asList("上海", "江苏", "浙江", "福建", "广东", "海南"));
        map.put("北上广深", Arrays.asList("北京", "上海"));
        map.put("偏远地区", Arrays.asList("新疆", "西藏", "宁夏", "甘肃", "青海", "内蒙古"));
        return Collections.unmodifiableMap(map);
    }

    private static Map<String, List<String>> buildAreaCities() {
        Map<String, List<String>> map = new LinkedHashMap<String, List<String>>();
        map.put("珠三角", Arrays.asList("广州", "深圳", "珠海", "佛山", "东莞", "中山", "惠州", "江门", "肇庆"));
        map.put("北上广深", Arrays.asList("北京", "上海", "广州", "深圳"));
        return Collections.unmodifiableMap(map);
    }
}
