package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.manager.MajorExtraDataManager;
import com.ytell.zhiyuan.model.vo.MajorExtraDataVO;
import io.swagger.annotations.Api;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 专业补充数据控制器
 * 提供专业补充数据查询接口
 */
@Slf4j
@RestController
@RequestMapping("/gaotu-assistant-bot/inner/major-extra-data")
@Api(tags = "内部使用接口")
public class MajorExtraDataController {

    @Autowired
    private MajorExtraDataManager majorExtraDataManager;

    /**
     * 多条件查询专业补充数据
     *
     * @param artsScienceList 文理报考情况列表（可选）
     * @param subjectList     优势学科列表（可选）
     * @param regionList      优势地域列表（可选）
     * @return 符合条件的专业补充数据列表
     */
    @GetMapping("/search")
    public BaseResponse<List<MajorExtraDataVO>> searchMajorExtraData(
            @RequestParam(required = false) List<String> artsScienceList,
            @RequestParam(required = false) List<String> subjectList,
            @RequestParam(required = false) List<String> regionList) {

        log.info("查询专业补充数据，文理报考情况: {}, 优势学科: {}, 优势地域: {}",
                artsScienceList, subjectList, regionList);

        try {
            List<MajorExtraDataVO> result = majorExtraDataManager.searchMajorExtraData(
                    artsScienceList, subjectList, regionList);

            log.info("查询专业补充数据完成，返回 {} 条数据", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("查询专业补充数据失败", e);
            return BaseResponse.error(500, "查询专业补充数据失败");
        }
    }

    /**
     * 根据一级分类查询专业补充数据
     *
     * @param firstCategory 一级分类
     * @return 该一级分类的专业补充数据列表
     */
    @GetMapping("/by-first-category")
    public BaseResponse<List<MajorExtraDataVO>> getByFirstCategory(
            @RequestParam String firstCategory) {

        log.info("根据一级分类查询专业补充数据: {}", firstCategory);

        try {
            List<MajorExtraDataVO> result = majorExtraDataManager.getByFirstCategory(firstCategory);

            log.info("根据一级分类查询专业补充数据完成，返回 {} 条数据", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("根据一级分类查询专业补充数据失败", e);
            return BaseResponse.error(500, "根据一级分类查询专业补充数据失败");
        }
    }

    /**
     * 根据二级分类查询专业补充数据
     *
     * @param secondCategory 二级分类
     * @return 该二级分类的专业补充数据列表
     */
    @GetMapping("/by-second-category")
    public BaseResponse<List<MajorExtraDataVO>> getBySecondCategory(
            @RequestParam String secondCategory) {

        log.info("根据二级分类查询专业补充数据: {}", secondCategory);

        try {
            List<MajorExtraDataVO> result = majorExtraDataManager.getBySecondCategory(secondCategory);

            log.info("根据二级分类查询专业补充数据完成，返回 {} 条数据", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("根据二级分类查询专业补充数据失败", e);
            return BaseResponse.error(500, "根据二级分类查询专业补充数据失败");
        }
    }

    /**
     * 根据文理报考情况查询专业补充数据
     *
     * @param artsScience 文理报考情况
     * @return 该文理报考情况的专业补充数据列表
     */
    @GetMapping("/by-arts-science")
    public BaseResponse<List<MajorExtraDataVO>> getByArtsScience(
            @RequestParam String artsScience) {

        log.info("根据文理报考情况查询专业补充数据: {}", artsScience);

        try {
            List<MajorExtraDataVO> result = majorExtraDataManager.getByArtsScience(artsScience);

            log.info("根据文理报考情况查询专业补充数据完成，返回 {} 条数据", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("根据文理报考情况查询专业补充数据失败", e);
            return BaseResponse.error(500, "根据文理报考情况查询专业补充数据失败");
        }
    }

    /**
     * 根据优势地域查询专业补充数据
     *
     * @param region 优势地域
     * @return 该优势地域的专业补充数据列表
     */
    @GetMapping("/by-advantage-region")
    public BaseResponse<List<MajorExtraDataVO>> getByAdvantageRegion(
            @RequestParam String region) {

        log.info("根据优势地域查询专业补充数据: {}", region);

        try {
            List<MajorExtraDataVO> result = majorExtraDataManager.getByAdvantageRegion(region);

            log.info("根据优势地域查询专业补充数据完成，返回 {} 条数据", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("根据优势地域查询专业补充数据失败", e);
            return BaseResponse.error(500, "根据优势地域查询专业补充数据失败");
        }
    }

    /**
     * 获取所有专业补充数据
     *
     * @return 所有专业补充数据列表
     */
    @GetMapping("/all")
    public BaseResponse<List<MajorExtraDataVO>> getAllMajorExtraData() {

        log.info("获取所有专业补充数据");

        try {
            List<MajorExtraDataVO> result = majorExtraDataManager.getAllMajorExtraData();

            log.info("获取所有专业补充数据完成，返回 {} 条数据", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("获取所有专业补充数据失败", e);
            return BaseResponse.error(500, "获取所有专业补充数据失败");
        }
    }

    /**
     * 获取所有一级分类
     *
     * @return 所有一级分类列表
     */
    @GetMapping("/first-categories")
    public BaseResponse<List<String>> getAllFirstCategories() {

        log.info("获取所有一级分类");

        try {
            List<String> result = majorExtraDataManager.getAllFirstCategories();

            log.info("获取所有一级分类完成，返回 {} 个分类", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("获取所有一级分类失败", e);
            return BaseResponse.error(500, "获取所有一级分类失败");
        }
    }

    /**
     * 获取所有二级分类
     *
     * @return 所有二级分类列表
     */
    @GetMapping("/second-categories")
    public BaseResponse<List<String>> getAllSecondCategories() {

        log.info("获取所有二级分类");

        try {
            List<String> result = majorExtraDataManager.getAllSecondCategories();

            log.info("获取所有二级分类完成，返回 {} 个分类", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("获取所有二级分类失败", e);
            return BaseResponse.error(500, "获取所有二级分类失败");
        }
    }

    /**
     * 获取所有文理报考情况
     *
     * @return 所有文理报考情况列表
     */
    @GetMapping("/arts-science")
    public BaseResponse<List<String>> getAllArtsScience() {

        log.info("获取所有文理报考情况");

        try {
            List<String> result = majorExtraDataManager.getAllArtsScience();

            log.info("获取所有文理报考情况完成，返回 {} 种情况", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("获取所有文理报考情况失败", e);
            return BaseResponse.error(500, "获取所有文理报考情况失败");
        }
    }

    /**
     * 获取所有优势地域
     *
     * @return 所有优势地域列表
     */
    @GetMapping("/advantage-regions")
    public BaseResponse<List<String>> getAllAdvantageRegions() {

        log.info("获取所有优势地域");

        try {
            List<String> result = majorExtraDataManager.getAllAdvantageRegions();

            log.info("获取所有优势地域完成，返回 {} 个地域", result.size());
            return BaseResponse.success(result);
        } catch (Exception e) {
            log.error("获取所有优势地域失败", e);
            return BaseResponse.error(500, "获取所有优势地域失败");
        }
    }

    /**
     * 获取专业补充数据统计信息
     *
     * @return 统计信息
     */
    @GetMapping("/statistics")
    public BaseResponse<Object> getStatistics() {

        log.info("获取专业补充数据统计信息");

        try {
            int totalCount = majorExtraDataManager.getTotalCount();
            int firstCategoryCount = majorExtraDataManager.getAllFirstCategories().size();
            int secondCategoryCount = majorExtraDataManager.getAllSecondCategories().size();
            int artsScienceCount = majorExtraDataManager.getAllArtsScience().size();
            int advantageRegionCount = majorExtraDataManager.getAllAdvantageRegions().size();

            java.util.Map<String, Object> statistics = new java.util.HashMap<>();
            statistics.put("totalCount", totalCount);
            statistics.put("firstCategoryCount", firstCategoryCount);
            statistics.put("secondCategoryCount", secondCategoryCount);
            statistics.put("artsScienceCount", artsScienceCount);
            statistics.put("advantageRegionCount", advantageRegionCount);

            log.info("获取专业补充数据统计信息完成");
            return BaseResponse.success(statistics);
        } catch (Exception e) {
            log.error("获取专业补充数据统计信息失败", e);
            return BaseResponse.error(500, "获取专业补充数据统计信息失败");
        }
    }
}
