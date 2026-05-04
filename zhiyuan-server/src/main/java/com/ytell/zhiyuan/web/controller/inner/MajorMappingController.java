package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.manager.MajorMappingManager;
import com.ytell.zhiyuan.model.dto.MajorInfo;
import com.ytell.zhiyuan.model.dto.MajorMappingResult;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 专业映射控制器
 * 提供专业映射查询接口
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/inner/major")
@Api(tags = "内部使用接口")
public class MajorMappingController {

    @Autowired
    private MajorMappingManager majorMappingManager;

    /**
     * 根据三级专业ID查询二级专业ID
     */
    @GetMapping("/getSecondLevelId")
    public String getSecondLevelIdByThirdLevelId(@RequestParam String thirdLevelId) {
        return majorMappingManager.getSecondLevelIdByThirdLevelId(thirdLevelId);
    }

    /**
     * 根据二级专业ID查询所有三级专业ID列表
     */
    @GetMapping("/getThirdLevelIds")
    public List<String> getThirdLevelIdsBySecondLevelId(@RequestParam String secondLevelId) {
        return majorMappingManager.getThirdLevelIdsBySecondLevelId(secondLevelId);
    }

    /**
     * 根据三级专业名字查询，三级专业id以及对应的二级专业id
     */
    @GetMapping("/getThirdLevelIdAndSecondLevelId")
    public List<MajorMappingResult> getThirdLevelIdAndSecondLevelId(@RequestParam String thirdLevelName) {
        return majorMappingManager.getThirdLevelIdAndSecondLevelId(thirdLevelName);
    }

    /**
     * 根据专业ID获取专业信息
     */
    @GetMapping("/getMajorInfo")
    public MajorInfo getMajorInfo(@RequestParam String majorId) {
        return majorMappingManager.getMajorInfo(majorId);
    }

    /**
     * 根据三级专业ID获取完整信息（包含二级专业信息）
     */
    @GetMapping("/getCompleteInfo")
    public Map<String, MajorInfo> getCompleteInfoByThirdLevelId(@RequestParam String thirdLevelId) {
        return majorMappingManager.getCompleteInfoByThirdLevelId(thirdLevelId);
    }

    /**
     * 获取映射统计信息
     */
    @GetMapping("/statistics")
    public Map<String, Object> getStatistics() {
        return majorMappingManager.getStatistics();
    }
} 