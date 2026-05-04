package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 学校信息控制器
 * 提供学校信息查询接口
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/inner/school")
@Api(tags = "内部使用接口")
public class SchoolController {

    @Autowired
    private SchoolManager schoolManager;

    /**
     * 根据学校ID查询学校信息
     */
    @GetMapping("/id")
    public SchoolVO getSchoolById(@RequestParam String schoolId) {
        return schoolManager.getSchoolById(schoolId);
    }

    /**
     * 根据学校名称查询学校信息
     */
    @GetMapping("/name")
    public SchoolVO getSchoolByName(@RequestParam String schoolName) {
        return schoolManager.getSchoolByName(schoolName);
    }

    /**
     * 根据学校名称模糊查询学校信息
     */
    @GetMapping("/search/name")
    public List<SchoolVO> searchSchoolsByName(@RequestParam String schoolName) {
        return schoolManager.searchSchoolsByName(schoolName);
    }

    /**
     * 根据省份查询学校列表
     */
    @GetMapping("/province")
    public List<SchoolVO> getSchoolsByProvince(@RequestParam String province) {
        return schoolManager.getSchoolsByProvince(province);
    }

    /**
     * 根据城市查询学校列表
     */
    @GetMapping("/city")
    public List<SchoolVO> getSchoolsByCity(@RequestParam String city) {
        return schoolManager.getSchoolsByCity(city);
    }

    /**
     * 根据学校类型查询学校列表
     */
    @GetMapping("/type")
    public List<SchoolVO> getSchoolsByType(@RequestParam String schoolType) {
        return schoolManager.getSchoolsByType(schoolType);
    }

    /**
     * 根据公办民办查询学校列表
     */
    @GetMapping("/ownership")
    public List<SchoolVO> getSchoolsByOwnership(@RequestParam String ownership) {
        return schoolManager.getSchoolsByOwnership(ownership);
    }

    /**
     * 根据本科专科查询学校列表
     */
    @GetMapping("/education-level")
    public List<SchoolVO> getSchoolsByEducationLevel(@RequestParam String educationLevel) {
        return schoolManager.getSchoolsByEducationLevel(educationLevel);
    }

    /**
     * 根据学校标签查询学校列表
     */
    @GetMapping("/tag")
    public List<SchoolVO> getSchoolsByTag(@RequestParam String tag) {
        return schoolManager.getSchoolsByTag(tag);
    }

    /**
     * 获取所有省份列表
     */
    @GetMapping("/provinces/all")
    public List<String> getAllProvinces() {
        return schoolManager.getAllProvinces();
    }

    /**
     * 获取所有城市列表
     */
    @GetMapping("/cities/all")
    public List<String> getAllCities() {
        return schoolManager.getAllCities();
    }

    /**
     * 获取所有学校类型列表
     */
    @GetMapping("/types/all")
    public List<String> getAllSchoolTypes() {
        return schoolManager.getAllSchoolTypes();
    }

    /**
     * 获取所有学校信息
     */
    @GetMapping("/all")
    public List<SchoolVO> getAllSchools() {
        return schoolManager.getAllSchools();
    }

    /**
     * 获取学校总数
     */
    @GetMapping("/count")
    public int getTotalSchoolCount() {
        return schoolManager.getTotalSchoolCount();
    }

    /**
     * 复合查询：根据多个条件查询学校
     */
    @GetMapping("/search/advanced")
    public List<SchoolVO> searchSchools(
            @RequestParam(required = false) String province,
            @RequestParam(required = false) String city,
            @RequestParam(required = false) String schoolType,
            @RequestParam(required = false) String ownership,
            @RequestParam(required = false) String educationLevel) {
        return schoolManager.searchSchools(province, city, schoolType, ownership, educationLevel);
    }
}
