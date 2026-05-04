package com.ytell.zhiyuan.manager;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.req.UnAcceptableMajorsReq;
import com.ytell.zhiyuan.model.vo.UnacceptableMajorVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 不能接受专业数据管理器
 * 提供不能接受专业数据的查询功能
 */
@Slf4j
@Component
public class UnacceptableMajorManager {

    /**
     * 不能接受专业数据缓存 - 使用List存储，避免相同majorId在不同学历层次下的覆盖问题
     */
    private final List<UnacceptableMajorVO> unacceptableMajorCache = new ArrayList<>();

    /**
     * 初始化加载不能接受专业数据
     */
    @PostConstruct
    public void init() {
        try {
            loadUnacceptableMajorData();
            log.info("不能接受专业数据加载完成，共加载 {} 个专业", unacceptableMajorCache.size());
        } catch (Exception e) {
            log.error("加载不能接受专业数据失败", e);
        }
    }

    /**
     * 加载不能接受专业数据
     * 这里使用从规划师那里拿到的专业类数据，实际项目中可以从数据库或配置文件加载
     */
    private void loadUnacceptableMajorData() {
        // 根据规划师提供的专业类数据更新
        List<UnacceptableMajorVO> unacceptableMajors = Arrays.asList(
            // WL填报类型专业类 - 01本科
            new UnacceptableMajorVO("2", "哲学类", "WL", "01"),
            new UnacceptableMajorVO("11", "社会学类", "WL", "01"),
            new UnacceptableMajorVO("16", "教育学类", "WL", "01"),
            new UnacceptableMajorVO("20", "外国语言文学类", "WL", "01"),
            new UnacceptableMajorVO("28", "化学类", "WL", "01"),
            new UnacceptableMajorVO("29", "天文学类", "WL", "01"),
            new UnacceptableMajorVO("31", "大气科学类", "WL", "01"),
            new UnacceptableMajorVO("32", "海洋科学类", "WL", "01"),
            new UnacceptableMajorVO("34", "地质学类", "WL", "01"),
            new UnacceptableMajorVO("35", "生物科学类", "WL", "01"),
            new UnacceptableMajorVO("42", "材料类", "WL", "01"),
            new UnacceptableMajorVO("49", "水利类", "WL", "01"),
            new UnacceptableMajorVO("50", "测绘类", "WL", "01"),
            new UnacceptableMajorVO("51", "化工与制药类", "WL", "01"),
            new UnacceptableMajorVO("53", "矿业类", "WL", "01"),
            new UnacceptableMajorVO("54", "纺织类", "WL", "01"),
            new UnacceptableMajorVO("61", "农业工程类", "WL", "01"),
            new UnacceptableMajorVO("63", "环境科学与工程类", "WL", "01"),
            new UnacceptableMajorVO("64", "生物医学工程类", "WL", "01"),
            new UnacceptableMajorVO("65", "食品科学与工程类", "WL", "01"),
            new UnacceptableMajorVO("66", "建筑类", "WL", "01"),
            new UnacceptableMajorVO("71", "植物生产类", "WL", "01"),
            new UnacceptableMajorVO("72", "自然保护与环境生态类", "WL", "01"),
            new UnacceptableMajorVO("75", "林学类", "WL", "01"),
            new UnacceptableMajorVO("76", "水产类", "WL", "01"),
            new UnacceptableMajorVO("77", "草学类", "WL", "01"),
            new UnacceptableMajorVO("79", "基础医学类", "WL", "01"),
            new UnacceptableMajorVO("80", "临床医学类", "WL", "01"),
            new UnacceptableMajorVO("81", "口腔医学类", "WL", "01"),
            new UnacceptableMajorVO("82", "公共卫生与预防医学类", "WL", "01"),
            new UnacceptableMajorVO("83", "中医学类", "WL", "01"),
            new UnacceptableMajorVO("84", "中西医结合类", "WL", "01"),
            new UnacceptableMajorVO("85", "药学类", "WL", "01"),
            new UnacceptableMajorVO("86", "中药学类", "WL", "01"),
            new UnacceptableMajorVO("87", "法医学类", "WL", "01"),
            new UnacceptableMajorVO("88", "医学技术类", "WL", "01"),
            new UnacceptableMajorVO("89", "护理学类", "WL", "01"),
            new UnacceptableMajorVO("94", "公共管理类", "WL", "01"),
            new UnacceptableMajorVO("99", "旅游管理类", "WL", "01"),

            // LS填报类型专业类 - 01本科
            new UnacceptableMajorVO("2", "哲学类", "LS", "01"),
            new UnacceptableMajorVO("10", "政治学类", "LS", "01"),
            new UnacceptableMajorVO("11", "社会学类", "LS", "01"),
            new UnacceptableMajorVO("12", "民族学类", "LS", "01"),
            new UnacceptableMajorVO("20", "外国语言文学类", "LS", "01"),
            new UnacceptableMajorVO("24", "历史学类", "LS", "01"),
            new UnacceptableMajorVO("95", "图书情报与档案管理类", "LS", "01"),
            new UnacceptableMajorVO("98", "电子商务类", "LS", "01"),
            new UnacceptableMajorVO("99", "旅游管理类", "LS", "01"),
            new UnacceptableMajorVO("79", "基础医学类", "LS", "01"),
            new UnacceptableMajorVO("80", "临床医学类", "LS", "01"),
            new UnacceptableMajorVO("81", "口腔医学类", "LS", "01"),
            new UnacceptableMajorVO("82", "公共卫生与预防医学类", "LS", "01"),
            new UnacceptableMajorVO("83", "中医学类", "LS", "01"),
            new UnacceptableMajorVO("84", "中西医结合类", "LS", "01"),
            new UnacceptableMajorVO("85", "药学类", "LS", "01"),
            new UnacceptableMajorVO("86", "中药学类", "LS", "01"),
            new UnacceptableMajorVO("87", "法医学类", "LS", "01"),
            new UnacceptableMajorVO("88", "医学技术类", "LS", "01"),
            new UnacceptableMajorVO("89", "护理学类", "LS", "01"),

            // WL填报类型专业类 - 02专科
            new UnacceptableMajorVO("209", "体育类", "WL", "02"),
            new UnacceptableMajorVO("132", "土建施工类", "WL", "02"),
            new UnacceptableMajorVO("134", "建设工程管理类", "WL", "02"),
            new UnacceptableMajorVO("130", "建筑设计类", "WL", "02"),
            new UnacceptableMajorVO("133", "建筑设备类", "WL", "02"),
            new UnacceptableMajorVO("136", "房地产类", "WL", "02"),
            new UnacceptableMajorVO("120", "安全类", "WL", "02"),
            new UnacceptableMajorVO("119", "环境保护类", "WL", "02"),
            new UnacceptableMajorVO("127", "非金属材料类", "WL", "02"),
            new UnacceptableMajorVO("126", "有色金属材料类", "WL", "02"),
            new UnacceptableMajorVO("117", "金属与非金属矿类", "WL", "02"),
            new UnacceptableMajorVO("181", "公共卫生与卫生管理类", "WL", "02"),
            new UnacceptableMajorVO("221", "公共服务类", "WL", "02"),
            new UnacceptableMajorVO("183", "健康管理与促进类", "WL", "02"),
            new UnacceptableMajorVO("160", "药品与医疗器械类", "WL", "02"),
            new UnacceptableMajorVO("201", "文化服务类", "WL", "02"),
            new UnacceptableMajorVO("199", "表演艺术类", "WL", "02"),
            new UnacceptableMajorVO("198", "艺术设计类", "WL", "02"),
            new UnacceptableMajorVO("1725", "旅游类", "WL", "02"),
            new UnacceptableMajorVO("107", "农业类", "WL", "02"),
            new UnacceptableMajorVO("108", "林业类", "WL", "02"),
            new UnacceptableMajorVO("195", "餐饮类", "WL", "02"),
            new UnacceptableMajorVO("207", "语言类", "WL", "02"),

            // LS填报类型专业类 - 02专科
            new UnacceptableMajorVO("209", "体育类", "LS", "02"),
            new UnacceptableMajorVO("132", "土建施工类", "LS", "02"),
            new UnacceptableMajorVO("134", "建设工程管理类", "LS", "02"),
            new UnacceptableMajorVO("130", "建筑设计类", "LS", "02"),
            new UnacceptableMajorVO("133", "建筑设备类", "LS", "02"),
            new UnacceptableMajorVO("136", "房地产类", "LS", "02"),
            new UnacceptableMajorVO("120", "安全类", "LS", "02"),
            new UnacceptableMajorVO("119", "环境保护类", "LS", "02"),
            new UnacceptableMajorVO("127", "非金属材料类", "LS", "02"),
            new UnacceptableMajorVO("126", "有色金属材料类", "LS", "02"),
            new UnacceptableMajorVO("117", "金属与非金属矿类", "LS", "02"),
            new UnacceptableMajorVO("181", "公共卫生与卫生管理类", "LS", "02"),
            new UnacceptableMajorVO("221", "公共服务类", "LS", "02"),
            new UnacceptableMajorVO("183", "健康管理与促进类", "LS", "02"),
            new UnacceptableMajorVO("160", "药品与医疗器械类", "LS", "02"),
            new UnacceptableMajorVO("201", "文化服务类", "LS", "02"),
            new UnacceptableMajorVO("199", "表演艺术类", "LS", "02"),
            new UnacceptableMajorVO("198", "艺术设计类", "LS", "02"),
            new UnacceptableMajorVO("1725", "旅游类", "LS", "02"),
            new UnacceptableMajorVO("107", "农业类", "LS", "02"),
            new UnacceptableMajorVO("108", "林业类", "LS", "02"),
            new UnacceptableMajorVO("195", "餐饮类", "LS", "02"),
            new UnacceptableMajorVO("207", "语言类", "LS", "02")
        );

            // 缓存不能接受专业数据
            unacceptableMajorCache.addAll(unacceptableMajors);
    }


    public  List<UnacceptableMajorVO> getByReq(UnAcceptableMajorsReq req){
        List<CreateSessionReq.SubjectItem> subjectList=req.getSubjectList();
        String subjectType=req.getSubjectType();
        if("N".equals(subjectType)){
            List<CreateSessionReq.SubjectItem>  filterSubjects= subjectList.stream().filter(one->{
                String subjectName=one.getName();
                if(subjectName!=null&&(subjectName.contains("物理")||subjectName.contains("化学"))){
                    return true;
                }else{
                    return false;
                }
            }).collect(Collectors.toList());
            if(filterSubjects.size()==2){
                subjectType="WL";
            }else{
                subjectType="LS";
            }
        }
        //新疆是文理
        if ("L".equals(subjectType)) {
            subjectType = "WL";
        }
        if ("W".equals(subjectType)) {
            subjectType = "LS";
        }
        if (Strings.isNullOrEmpty(subjectType)) {
            subjectType = "WL";
        }
        if (!"WL".equals(subjectType) && !"LS".equals(subjectType)) {
            subjectType = "WL";
        }
        return this.getBySubjectTypeAndEducationLevel(req.getEducationLevel(), subjectType);

    }

    /**
     * 根据填报类型和学历层次获取不能接受的专业类列表
     *
     * @param subjectType 填报类型 (WL-物理, LS-历史,N-综合)
     * @param educationLevel 学历层次 (01-本科, 02-专科，也支持中文：本科、专科)，为null时返回所有学历层次
     * @return 对应填报类型和学历层次的专业类列表
     */
    public List<UnacceptableMajorVO> getBySubjectTypeAndEducationLevel( String educationLevel,String subjectType) {
        if (subjectType == null || subjectType.trim().isEmpty()) {
            return new ArrayList<>();
        }
        String type = subjectType.trim();

        return unacceptableMajorCache.stream()
                .filter(major -> type.equals(major.getSubjectType()) &&
                               (educationLevel == null || educationLevel.equals(major.getEducationLevel())))
                .sorted(Comparator.comparing(UnacceptableMajorVO::getMajorId))
                .collect(Collectors.toList());
    }

 
}
