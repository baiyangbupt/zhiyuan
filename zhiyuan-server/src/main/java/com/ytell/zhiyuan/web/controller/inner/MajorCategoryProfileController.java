package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.manager.MajorCategoryProfileManager;
import com.ytell.zhiyuan.model.dto.MajorCategoryProfileDto;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/major-category")
@Api(tags = "内部使用接口")
public class MajorCategoryProfileController {

    @Autowired
    private MajorCategoryProfileManager majorCategoryProfileManager;

    @GetMapping("/getMajorCategoryProfile")
    @ApiOperation(value = "获取专业类概述信息", notes = "获取专业类概述信息")
    public MajorCategoryProfileDto getMajorCategoryProfileByName(
            @RequestParam(value = "name",required = false) String name,
            @RequestParam(value = "id",required = false) String id) {
        return majorCategoryProfileManager.getMajorCategoryProfile(name,id);
    }

    @GetMapping("/getAllMajorCategoryProfiles")
    @ApiOperation(value = "获取所有专业类概述信息", notes = "获取系统中所有专业类的概述信息列表")
    public List<MajorCategoryProfileDto> getAllMajorCategoryProfiles() {
        return majorCategoryProfileManager.getAllMajorCategoryProfiles();
    }

    @GetMapping("/searchMajorCategoryProfiles")
    @ApiOperation(value = "模糊查询专业类概述信息", notes = "根据专业类名称关键字模糊查询相关专业类信息")
    public List<MajorCategoryProfileDto> searchMajorCategoryProfiles(
            @ApiParam(value = "专业类名称关键字", required = true) @RequestParam String keyword) {
        return majorCategoryProfileManager.getMajorCategoryProfilesByName(keyword);
    }

    @GetMapping("/getAllMajorCategoryNames")
    @ApiOperation(value = "获取所有专业类名称", notes = "获取系统中所有专业类的名称列表")
    public List<String> getAllMajorCategoryNames() {
        return majorCategoryProfileManager.getAllMajorCategoryNames();
    }

    @GetMapping("/existsMajorCategory")
    @ApiOperation(value = "检查专业类是否存在", notes = "检查指定的专业类名称在系统中是否存在")
    public boolean existsMajorCategory(
            @ApiParam(value = "专业类名称", required = true) @RequestParam String categoryName) {
        return majorCategoryProfileManager.existsMajorCategory(categoryName);
    }

    @GetMapping("/getMajorCategoryProfileCount")
    @ApiOperation(value = "获取专业类总数", notes = "获取系统中专业类概述数据的总数量")
    public int getMajorCategoryProfileCount() {
        return majorCategoryProfileManager.getMajorCategoryProfileCount();
    }
}
