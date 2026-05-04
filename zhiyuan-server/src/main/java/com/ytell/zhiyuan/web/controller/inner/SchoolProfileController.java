package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.manager.SchoolProfileManager;
import com.ytell.zhiyuan.model.dto.SchoolProfileDto;
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
@RequestMapping("/gaotu-assistant-bot/inner/school")
@Api(tags = "内部使用接口")
public class SchoolProfileController {

    @Autowired
    private SchoolProfileManager schoolProfileManager;

    @GetMapping("/getSchoolProfileByName")
    @ApiOperation("根据学校名称获取学校画像信息")
    public SchoolProfileDto getSchoolProfileByName(@ApiParam("学校名称") @RequestParam String name) {
        return schoolProfileManager.getSchoolProfileByName(name);
    }

    @GetMapping("/getAllSchoolProfiles")
    @ApiOperation("获取所有学校画像数据")
    public List<SchoolProfileDto> getAllSchoolProfiles() {
        return schoolProfileManager.getAllSchoolProfiles();
    }

    @GetMapping("/getSchoolProfilesByName")
    @ApiOperation("根据学校名称模糊查询学校画像")
    public List<SchoolProfileDto> getSchoolProfilesByName(@ApiParam("学校名称") @RequestParam String name) {
        return schoolProfileManager.getSchoolProfilesByName(name);
    }

    @GetMapping("/getSchoolProfilesByProvince")
    @ApiOperation("根据省份获取学校画像列表")
    public List<SchoolProfileDto> getSchoolProfilesByProvince(@ApiParam("省份") @RequestParam String province) {
        return schoolProfileManager.getSchoolProfilesByProvince(province);
    }

    @GetMapping("/getSchoolProfilesByCity")
    @ApiOperation("根据城市获取学校画像列表")
    public List<SchoolProfileDto> getSchoolProfilesByCity(@ApiParam("城市") @RequestParam String city) {
        return schoolProfileManager.getSchoolProfilesByCity(city);
    }

    @GetMapping("/getSchoolProfilesByLevel")
    @ApiOperation("根据办学层次获取学校画像列表")
    public List<SchoolProfileDto> getSchoolProfilesByLevel(@ApiParam("办学层次") @RequestParam String level) {
        return schoolProfileManager.getSchoolProfilesByLevel(level);
    }

    @GetMapping("/getSchoolProfilesByNature")
    @ApiOperation("根据办学性质获取学校画像列表")
    public List<SchoolProfileDto> getSchoolProfilesByNature(@ApiParam("办学性质") @RequestParam String nature) {
        return schoolProfileManager.getSchoolProfilesByNature(nature);
    }

    @GetMapping("/getSchoolProfilesByCategory")
    @ApiOperation("根据学校类别获取学校画像列表")
    public List<SchoolProfileDto> getSchoolProfilesByCategory(@ApiParam("学校类别") @RequestParam String category) {
        return schoolProfileManager.getSchoolProfilesByCategory(category);
    }

    @GetMapping("/getSchoolProfilesByBatch")
    @ApiOperation("根据录取批次获取学校画像列表")
    public List<SchoolProfileDto> getSchoolProfilesByBatch(@ApiParam("录取批次") @RequestParam String batch) {
        return schoolProfileManager.getSchoolProfilesByBatch(batch);
    }

    @GetMapping("/getSchoolProfileCount")
    @ApiOperation("获取学校画像数据总数")
    public int getSchoolProfileCount() {
        return schoolProfileManager.getSchoolProfileCount();
    }
}
