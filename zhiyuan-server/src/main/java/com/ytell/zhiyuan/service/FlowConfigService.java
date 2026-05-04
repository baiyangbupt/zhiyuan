package com.ytell.zhiyuan.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.manager.EthnicityManager;
import com.ytell.zhiyuan.manager.MajorMappingManager;
import com.ytell.zhiyuan.manager.ProvinceCityManager;
import com.ytell.zhiyuan.manager.UnacceptableMajorManager;
import com.ytell.zhiyuan.model.dto.MajorInfo;
import com.ytell.zhiyuan.model.vo.*;
import com.ytell.zhiyuan.service.biz.UserBizService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 高考志愿填报流程配置服务
 */
@Service
@Slf4j
public class FlowConfigService {

    @Value("classpath:bizdata/gaokao_volunteer_flow_config.json")
    private Resource configResource;
    @Autowired
    private UserBizService userBizService;
    @Autowired
    private ProvinceCityManager provinceCityManager;

    @Autowired
    private MajorMappingManager majorMappingManager;

    @Autowired
    private EthnicityManager ethnicityManager;
    @Autowired
    private UnacceptableMajorManager unacceptableMajorManager;
    private JSONObject templateConfig;

    // 预加载的选项数据
    private JSONArray provinceOptions;
    private JSONArray bachelorMajorOptions;
    private JSONArray associateMajorOptions;
    private JSONArray ethnicityOptions;
    private JSONArray regionOptions;

    private JSONArray examYearOptions;


    @PostConstruct
    public void init() {
        loadConfig();
        preloadStaticOptions();
        processConfig();
    }

    /**
     * 加载配置文件
     */
    private void loadConfig() {
        try (InputStream inputStream = configResource.getInputStream();
             BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8))) {

            StringBuilder content = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                content.append(line).append("\n");
            }
            this.templateConfig = JSON.parseObject(content.toString());
            log.info("Successfully loaded flow config from: {}", configResource.getFilename());
        } catch (IOException e) {
            log.error("Failed to load flow config from: {}", configResource.getFilename(), e);
            throw new RuntimeException("Failed to load flow config", e);
        }
    }

    /**
     * 预加载静态选项数据
     */
    private void preloadStaticOptions() {
        try {
            // 预加载省份选项
            provinceOptions = loadProvinceOptions();
            // 预加载专业选项（本科/专科）
            bachelorMajorOptions = loadMajorOptions(MajorMappingManager.EducationLevel.BACHELOR);
            associateMajorOptions = loadMajorOptions(MajorMappingManager.EducationLevel.ASSOCIATE);
            // 预加载民族选项
            ethnicityOptions = loadEthnicityOptions();
            // 预加载区选项
            regionOptions = createRegionOptions();
            //
            examYearOptions= loadExamYearField();

            log.info("Successfully preloaded static options");
        } catch (Exception e) {
            log.error("Failed to preload static options", e);
            throw new RuntimeException("Failed to preload static options", e);
        }
    }

    /**
     * 处理配置数据，补全属性和默认值
     */
    private void processConfig() {
        if (templateConfig == null) {
            return;
        }

        log.info("Successfully processed flow config template");
    }

    /**
     * 根据用户信息获取填充后的流程配置
     * @return 填充了用户数据和选项数据的完整配置
     */
    public JSONObject getFlowConfigWithUserData(Long userId) {

        UserVO userVO = userBizService.getUserVoById(userId);

        // 从用户数据中提取信息
        Map<String, Object> userInfo = extractUserInfo(userVO);
        log.info("userInfo:{}",userInfo);

        // 总是调用填充方法，确保返回完整的配置
        JSONObject userInfoJson = JSONObject.parseObject(JSONObject.toJSONString(userInfo));

        // 深拷贝模板，避免修改原始模板
        JSONObject filledConfig = JSON.parseObject(templateConfig.toJSONString());

        // 填充配置数据（用户数据 + 选项数据 + 动态用户字段）
        fillConfigData(filledConfig, userInfoJson);

        return filledConfig;
    }
    private Map<String, Object> extractUserInfo(UserVO userVO) {
        Map<String, Object> userInfo = new HashMap<>();

        if (userVO == null || userVO.getUserScoreOb() == null) {
            return userInfo;
        }

        // 提取高考省份信息
        if (userVO.getUserScoreOb().getProvince() != null) {
            userInfo.put("examProvince", userVO.getUserScoreOb().getProvince().getCode());
        }

        // 提取高考年份信息
        if (userVO.getUserScoreOb().getExamYear() != null) {
            userInfo.put("examYear", String.valueOf(userVO.getUserScoreOb().getExamYear()));
        }

        // 提取性别信息
        if (userVO.getUserScoreOb().getSex() != null) {
            userInfo.put("sex", userVO.getUserScoreOb().getSex().getCode());
        }

        // 提取科目信息
        if (userVO.getUserScoreOb().getSubjectList() != null && !userVO.getUserScoreOb().getSubjectList().isEmpty()) {
            userInfo.put("subjectList", userVO.getUserScoreOb().getSubjectList());
        }
        // 提取选科信息
        if (userVO.getUserScoreOb().getSubjectType() != null ) {
            userInfo.put("subjectType", userVO.getUserScoreOb().getSubjectType().getCode());
        }
        // 提取科目成绩信息（需要从其他地方获取）
        // 这里暂时留空，实际实现中需要从用户相关数据中获取

        return userInfo;
    }
    /**
     * 填充配置数据（用户数据 + 选项数据 + 动态用户字段）
     */
    private void fillConfigData(JSONObject config, JSONObject userInfo) {
        if (config == null) {
            return;
        }

        // 遍历所有主要步骤
        JSONArray majorSteps = config.getJSONArray("majorSteps");
        if (majorSteps != null) {
            for (Object majorStepObj : majorSteps) {
                JSONObject majorStep = (JSONObject) majorStepObj;
                JSONArray subSteps = majorStep.getJSONArray("subSteps");
                if (subSteps != null) {
                    for (Object subStepObj : subSteps) {
                        JSONObject subStep = (JSONObject) subStepObj;
                        fillSubStepConfigData(subStep, userInfo);
                        // 处理summarySegments中的动态内容
                        fillSummarySegments(subStep, userInfo);
                    }
                }
            }
        }
    }

    /**
     * 填充summarySegments中的动态内容
     */
    private void fillSummarySegments(JSONObject subStep, JSONObject userInfo) {
        JSONArray summarySegments = subStep.getJSONArray("summarySegments");
        if (summarySegments == null) {
            return;
        }

        for (Object segmentObj : summarySegments) {
            JSONObject segment = (JSONObject) segmentObj;
            String segmentType = segment.getString("type");
            
            if ("image".equals(segmentType)) {
                // 处理图片类型的segment，替换URL中的占位符
                processImageSegment(segment, userInfo);
            }
        }
    }

    /**
     * 处理图片类型的segment，替换URL和标题中的占位符
     */
    private void processImageSegment(JSONObject segment, JSONObject userInfo) {
        String materialUrl = segment.getString("materialUrl");
        if (materialUrl != null && materialUrl.contains("#{provinceCode}")) {
            // 获取用户选择的省份代码
            String provinceCode = userInfo.getString("examProvince");
            if (provinceCode != null) {
                // 直接使用省份代码替换URL中的占位符
                String newUrl = materialUrl.replace("#{provinceCode}", provinceCode);
                segment.put("materialUrl", newUrl);
                
                // 更新content中的标题
                JSONObject content = segment.getJSONObject("content");
                if (content != null) {
                    String title = content.getString("title");
                    if (title != null && title.contains("#{provinceName}")) {
                        // 根据省份代码获取省份名称
                        String provinceName = provinceCityManager.getProvinceLabelById(provinceCode);
                        
                        if (provinceName != null) {
                            String newTitle = title.replace("#{provinceName}", provinceName);
                            content.put("title", newTitle);
                        }
                    }
                }
            }
        }
    }

    /**
     * 填充子步骤的配置数据
     */
    private void fillSubStepConfigData(JSONObject subStep, JSONObject userInfo) {
        JSONObject formConfig = subStep.getJSONObject("formConfig");
        if (formConfig == null) {
            return;
        }

        JSONArray fields = formConfig.getJSONArray("fields");
        if (fields == null) {
            return;
        }

        for (Object fieldObj : fields) {
            JSONObject field = (JSONObject) fieldObj;
            String fieldId = field.getString("fieldId");

            // 1. 根据用户数据设置字段默认值和可编辑性
            fillUserDataField(field, fieldId, userInfo);

            // 2. 填充静态选项数据
            fillOptionDataField(field, fieldId);

            // 3. 动态填充特殊用户字段
            fillUserSpecificField(field, fieldId, userInfo);
        }
    }

    /**
     * 根据用户数据设置字段默认值和可编辑性
     */
    private void fillUserDataField(JSONObject field, String fieldId, JSONObject userInfo) {
        switch (fieldId) {
            case "examProvince":
                if (userInfo.containsKey("examProvince")) {
                    field.put("defaultValue", userInfo.getString("examProvince"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", "");
                    field.put("editable", true);
                }
                break;
            case "examYear":
                if (userInfo.containsKey("examYear")) {
                    field.put("defaultValue", userInfo.getString("examYear"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", String.valueOf(java.time.Year.now().getValue() + 1));
                    field.put("editable", true);
                }
                break;
            case "sex":
                if (userInfo.containsKey("sex")) {
                    field.put("defaultValue", userInfo.getString("sex"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", "");
                    field.put("editable", true);
                }
                break;
            case "height":
                if (userInfo.containsKey("height")) {
                    field.put("defaultValue", userInfo.getString("height"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", "");
                    field.put("editable", true);
                }
                break;
            case "preferredMajors":
                if (userInfo.containsKey("preferredMajors")) {
                    field.put("defaultValue", userInfo.getJSONArray("preferredMajors"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", new JSONArray());
                    field.put("editable", true);
                }
                break;
            case "preferredRegions":
                if (userInfo.containsKey("preferredRegions")) {
                    field.put("defaultValue", userInfo.getJSONArray("preferredRegions"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", new JSONArray());
                    field.put("editable", true);
                }
                break;
            case "ethnicity":
                if (userInfo.containsKey("ethnicity")) {
                    field.put("defaultValue", userInfo.getString("ethnicity"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", "");
                    field.put("editable", true);
                }
                break;
            case "strengthSubjectList":
                if (userInfo.containsKey("strengthSubjectList")) {
                    field.put("defaultValue", userInfo.getJSONArray("strengthSubjectList"));
                    field.put("editable", false);
                } else {
                    field.put("defaultValue", new JSONArray());
                    field.put("editable", true);
                }
                break;
        }
    }

    /**
     * 填充静态选项数据
     */
    private void fillOptionDataField(JSONObject field, String fieldId) {
        switch (fieldId) {
            case "examProvince":
                if (provinceOptions != null) {
                    field.put("options", provinceOptions);
                }
                break;
            case "examYear":
                if (examYearOptions != null) {
                    field.put("options", examYearOptions);
                }
                break;
            case "ethnicity":
                if (ethnicityOptions != null) {
                    field.put("options", ethnicityOptions);
                }
                break;
            case "preferredMajors":
                if (bachelorMajorOptions != null) {
                    field.put("bachelorMajors", bachelorMajorOptions);
                }
                if (associateMajorOptions != null) {
                    field.put("associateMajors", associateMajorOptions);
                }
                // 兼容旧字段，默认返回本科数据
                if (bachelorMajorOptions != null) {
                    field.put("majors", bachelorMajorOptions);
                } else if (associateMajorOptions != null) {
                    field.put("majors", associateMajorOptions);
                }
                break;
            case "preferredRegions":
                if (regionOptions != null) {
                    field.put("regions", regionOptions);
                }
                break;
        }
    }

    /**
     * 动态填充特殊用户字段
     */
    private void fillUserSpecificField(JSONObject field, String fieldId, JSONObject userInfo) {
        switch (fieldId) {
            case "subjectList":
                if (userInfo != null && userInfo.containsKey("subjectList")) {
                    field.put("editable", false);
                    field.put("defaultValue", userInfo.getJSONArray("subjectList"));
                    
                    // 检查是否为浙江用户（省份代码330000）
                    if (userInfo.containsKey("examProvince") && "330000".equals(userInfo.getString("examProvince"))) {
                        // 为浙江用户在options中添加技术科目选项
                        addZhejiangTechSubjectToOptions(field);
                    }
                }
                break;
            case "subjectScoreList":
                // 根据用户的subjectList动态生成subjectScoreList
                JSONArray subjectScoreList = generateSubjectScoreList(userInfo);
                if (subjectScoreList != null) {
                    field.put("inputList", subjectScoreList);
                }
                break;
            case "strengthSubjectList":
                // 根据用户的subjectList动态生成strengthSubjectList的options
                JSONArray strengthSubjectOptions = generateStrengthSubjectOptions(userInfo);
                if (strengthSubjectOptions != null) {
                    field.put("options", strengthSubjectOptions);
                }
                break;
            case "unacceptableMajors":
                JSONObject unacceptableMajorOptions = generateUnacceptableMajorOptions(userInfo);
                if (unacceptableMajorOptions != null) {
                    if (unacceptableMajorOptions.containsKey("bachelorMajors")) {
                        field.put("bachelorMajors", unacceptableMajorOptions.getJSONArray("bachelorMajors"));
                    }
                    if (unacceptableMajorOptions.containsKey("associateMajors")) {
                        field.put("associateMajors", unacceptableMajorOptions.getJSONArray("associateMajors"));
                    }
                }
                break;

        }
    }

    /**
     * 根据用户的subjectList动态生成subjectScoreList
     * subjectScoreList = 用户选择的科目 + 固定三门（语文、数学、外语）
     */
    private JSONArray generateSubjectScoreList(JSONObject userInfo) {
        if (userInfo == null || !userInfo.containsKey("subjectList")) {
            return null;
        }

        try {
            JSONArray result = new JSONArray();

            // 添加固定三门科目
            addFixedSubjects(result);

            // 添加用户选择的科目
            JSONArray userSubjects = userInfo.getJSONArray("subjectList");
            if (userSubjects != null) {
                for (Object subjectObj : userSubjects) {
                    JSONObject subject = (JSONObject) subjectObj;
                    JSONObject scoreItem = new JSONObject();
                    scoreItem.put("score", 0); // 默认分数为0

                    // 处理两种不同的数据结构
                    String subjectCode = subject.getString("subject");
                    String subjectName = subject.getString("subjectName");

                    //如果没有subjectCode，尝试从value里取
                    if(subjectCode==null){
                        subjectCode=subject.getString("value");
                    }

                    // 如果没有subjectName字段，尝试从name字段获取
                    if (subjectName == null) {
                        subjectName = subject.getString("name");
                    }

                    scoreItem.put("subject", subjectCode);
                    scoreItem.put("subjectName", subjectName);
                    result.add(scoreItem);
                }
            }

            return result;
        } catch (Exception e) {
            log.error("Failed to generate subjectScoreList", e);
            return null;
        }
    }

    /**
     * 根据用户的subjectList动态生成strengthSubjectList的options
     */
    private JSONArray generateStrengthSubjectOptions(JSONObject userInfo) {
        if (userInfo == null || !userInfo.containsKey("subjectList")) {
            return null;
        }

        try {
            JSONArray result = new JSONArray();

            // 添加固定三门科目
            addFixedSubjectsToStrengthOptions(result);

            // 获取用户选择的科目
            JSONArray userSubjects = userInfo.getJSONArray("subjectList");
            if (userSubjects != null) {
                for (Object subjectObj : userSubjects) {
                    JSONObject subject = (JSONObject) subjectObj;
                    JSONObject option = new JSONObject();

                    // 复制完整的科目信息，保持与subjectList相同的数据结构
                    Integer isFirst = subject.getInteger("isFirst");
                    String subjectCode = subject.getString("subject");
                    String subjectName = subject.getString("subjectName");

                    // 如果没有subjectCode，尝试从value里取
                    if (subjectCode == null) {
                        subjectCode = subject.getString("value");
                    }

                    // 如果没有subjectName字段，尝试从name字段获取
                    if (subjectName == null) {
                        subjectName = subject.getString("name");
                    }

                    // 如果还是没有名称，使用默认值
                    if (subjectName == null) {
                        subjectName = "未知科目";
                    }

                    option.put("isFirst", isFirst);
                    option.put("subject", subjectCode);
                    option.put("subjectName", subjectName);
                    result.add(option);
                }
            }

            return result;
        } catch (Exception e) {
            log.error("Failed to generate strengthSubjectOptions", e);
            return null;
        }
    }

    /**
     * 为浙江用户在subjectList字段的options中添加技术科目选项
     */
    private void addZhejiangTechSubjectToOptions(JSONObject field) {
        try {
            // 获取现有的options数组
            JSONArray options = field.getJSONArray("options");
            if (options == null) {
                options = new JSONArray();
                field.put("options", options);
            }
            
            // 检查是否已经包含技术科目，避免重复添加
            boolean hasTechSubject = false;
            for (Object optionObj : options) {
                if (optionObj instanceof JSONObject) {
                    JSONObject option = (JSONObject) optionObj;
                    String subjectCode = option.getString("subject");
                    if ("07".equals(subjectCode)) {
                        hasTechSubject = true;
                        break;
                    }
                }
            }
            
            // 如果没有技术科目，则添加到options中
            if (!hasTechSubject) {
                JSONObject techSubject = new JSONObject();
                techSubject.put("isFirst", 0);
                techSubject.put("subject", "07");
                techSubject.put("subjectName", "技术");
                options.add(techSubject);
            }
        } catch (Exception e) {
            log.error("Failed to add Zhejiang tech subject to options", e);
        }
    }

    /**
     * 添加固定三门科目到strengthSubjectList的options
     */
    private void addFixedSubjectsToStrengthOptions(JSONArray result) {
        // 语文
        JSONObject chinese = new JSONObject();
        chinese.put("isFirst", 1);
        chinese.put("subject", "08");
        chinese.put("subjectName", "语文");
        result.add(chinese);

        // 数学
        JSONObject math = new JSONObject();
        math.put("isFirst", 1);
        math.put("subject", "10");
        math.put("subjectName", "数学");
        result.add(math);

        // 外语
        JSONObject english = new JSONObject();
        english.put("isFirst", 1);
        english.put("subject", "11");
        english.put("subjectName", "英语");
        result.add(english);
    }

    /**
     * 添加固定三门科目到subjectScoreList
     */
    private void addFixedSubjects(JSONArray result) {
        // 语文
        JSONObject chinese = new JSONObject();
        chinese.put("score", 0);
        chinese.put("subject", "08");
        chinese.put("subjectName", "语文");
        result.add(chinese);

        // 数学
        JSONObject math = new JSONObject();
        math.put("score", 0);
        math.put("subject", "10");
        math.put("subjectName", "数学");
        result.add(math);

        // 外语
        JSONObject english = new JSONObject();
        english.put("score", 0);
        english.put("subject", "11");
        english.put("subjectName", "英语");
        result.add(english);
    }


    /**
     * 填充高考年份字段
     */
    private JSONArray loadExamYearField() {
        // 年份选项可以写死，当前年份和下一年
        JSONArray options = new JSONArray();
        int currentYear = java.time.Year.now().getValue();
        int nextYear = currentYear + 1;

        JSONObject option1 = new JSONObject();
        option1.put("code", String.valueOf(nextYear));
        option1.put("name", nextYear + "年");
        options.add(option1);

        int nextNextYear = nextYear + 1;
        JSONObject option2 = new JSONObject();
        option2.put("value", String.valueOf(nextNextYear));
        option2.put("label", nextNextYear + "年");
        options.add(option2);

        int nextNextNextYear = nextNextYear + 1;
        JSONObject option3 = new JSONObject();
        option3.put("value", String.valueOf(nextNextNextYear));
        option3.put("label", nextNextNextYear + "年");
        options.add(option3);

        int nextNextNextNextYear = nextNextNextYear + 1;
        JSONObject option4 = new JSONObject();
        option4.put("value", String.valueOf(nextNextNextNextYear));
        option4.put("label", nextNextNextNextYear + "年");
        options.add(option4);

    return  options;
    }

    /**
     * 预加载省份选项
     */
    private JSONArray loadProvinceOptions(){
        List<ProvinceCityVO> provinces = provinceCityManager.getAllProvinces();
        JSONArray options = new JSONArray();

        for (ProvinceCityVO province : provinces) {
            JSONObject option = new JSONObject();
            option.put("code", province.getId());
            option.put("name", province.getLabel());
            options.add(option);
        }

        return options;
    }

    /**
     * 预加载专业选项-一级&二级
     */
    private JSONArray loadMajorOptions(MajorMappingManager.EducationLevel educationLevel)  {
        List<MajorInfo> majors = majorMappingManager.getTwoLevelAllMajors(educationLevel);
        JSONArray options = new JSONArray();
        for (MajorInfo major : majors) {
            JSONObject option = new JSONObject();
            option.put("value", major.getId());
            option.put("label", major.getLabel());
            option.put("children",major.getChildren().stream().map(one->{
                JSONObject childOption = new JSONObject();
                childOption.put("value", one.getId());
                childOption.put("label", one.getLabel());
                return childOption;
            }).collect(Collectors.toList()));
            options.add(option);
        }

        return options;
    }

    /**
     * 预加载民族选项
     */
    private JSONArray loadEthnicityOptions()  {
        List<EthnicityVO> ethnicities = ethnicityManager.getAllEthnicities();
        JSONArray options = new JSONArray();

        for (EthnicityVO ethnicity : ethnicities) {
            JSONObject option = new JSONObject();
            option.put("code", ethnicity.getCode());
            option.put("name", ethnicity.getName());
            options.add(option);
        }

        return options;
    }
    /**
     * 创建地区选项
     */
    private JSONArray createRegionOptions() {
        List<RegionProvinceVO> regionProvinceList = provinceCityManager.getRegionProvinceList();
        JSONArray regions = new JSONArray();

        for (RegionProvinceVO regionProvince : regionProvinceList) {
            JSONObject region = new JSONObject();
            region.put("regionId", regionProvince.getRegionName().replace("地区", "").toLowerCase().replace("华", ""));
            region.put("regionName", regionProvince.getRegionName());

            JSONArray provinces = new JSONArray();
            for (ProvinceCityVO province : regionProvince.getProvinces()) {
                JSONObject provinceOption = new JSONObject();
                provinceOption.put("name",province.getLabel());
                provinceOption.put("code",province.getId());
                provinces.add(provinceOption);
            }
            region.put("provinces", provinces);

            regions.add(region);
        }

        return regions;
    }

    private JSONObject  generateUnacceptableMajorOptions(JSONObject userInfo){
        String subjectType=userInfo.getString("subjectType");
        JSONArray subjectList=userInfo.getJSONArray("subjectList");
        log.info("generateUnacceptableMajorOptions - subjectType: {}, subjectList: {}", subjectType, subjectList);
        if("N".equals(subjectType) && subjectList != null){
          List<Object>  filterSubjects= subjectList.stream()
                  .filter(one->{
            try {
                JSONObject job;
                if (one instanceof JSONObject) {
                    job = (JSONObject) one;
                } else {
                    // 如果不是 JSONObject，尝试转换
                    job = JSONObject.parseObject(JSONObject.toJSONString(one));
                }
                String subjectName=job.getString("name");
                if(subjectName!=null&&(subjectName.contains("物理")||subjectName.contains("化学"))){
                    return true;
                }else{
                    return false;
                }
            } catch (Exception e) {
                log.warn("处理科目列表项时出错: {}", e.getMessage());
                return false;
            }
            }).collect(Collectors.toList());

            log.info("filterSubjects.size(): {}", filterSubjects.size());
            if(filterSubjects.size()==2){
                subjectType="WL";
            }else{
                subjectType="LS";
            }

        }
        //新疆是文理
        if("L".equals(subjectType)){
            subjectType="WL";
        }
        if("W".equals(subjectType)){
            subjectType="LS";
        }
        // 设置默认值
        if (subjectType == null || subjectType.trim().isEmpty()) {
            subjectType = "WL";
        }
        if (!"WL".equals(subjectType) && !"LS".equals(subjectType)) {
            subjectType = "WL";
        }
        log.info("最终 subjectType: {}", subjectType);

        // 获取本科批数据（01）
        List<UnacceptableMajorVO> bachelorMajors = unacceptableMajorManager.getBySubjectTypeAndEducationLevel("01", subjectType);
        JSONArray bachelorOptions = new JSONArray();
        for (UnacceptableMajorVO major : bachelorMajors) {
            JSONObject option = new JSONObject();
            option.put("value", major.getMajorId());
            option.put("label", major.getMajorName());
            bachelorOptions.add(option);
        }

        // 获取专科批数据（02）
        List<UnacceptableMajorVO> associateMajors = unacceptableMajorManager.getBySubjectTypeAndEducationLevel("02", subjectType);
        log.info("获取专科批数据，subjectType: {}, 数据量: {}", subjectType, associateMajors != null ? associateMajors.size() : 0);
        JSONArray associateOptions = new JSONArray();
        if (associateMajors != null) {
            for (UnacceptableMajorVO major : associateMajors) {
                JSONObject option = new JSONObject();
                option.put("value", major.getMajorId());
                option.put("label", major.getMajorName());
                associateOptions.add(option);
            }
        }

        JSONObject result = new JSONObject();
        result.put("bachelorMajors", bachelorOptions);
        result.put("associateMajors", associateOptions);
        log.info("generateUnacceptableMajorOptions 返回结果，本科批数量: {}, 专科批数量: {}", bachelorOptions.size(), associateOptions.size());
        return result;
    }

}
