package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.model.dto.catalog.CatalogFilterTagsTreeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorTreeNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogRegionTreeNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogResponseDTO;
import com.ytell.zhiyuan.service.biz.CatalogService;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/catalog")
@Api(tags = "内部使用接口")
public class CatalogController {

    @Autowired
    private CatalogService catalogService;

    @GetMapping("/lookup/school")
    public CatalogResponseDTO<?> lookupSchool(@RequestParam String name) {
        return catalogService.lookupSchool(name);
    }

    @GetMapping("/lookup/major")
    public CatalogResponseDTO<?> lookupMajor(@RequestParam String name,
                                             @RequestParam(required = false) String educationLevel) {
        return catalogService.lookupMajor(name, educationLevel);
    }

    @GetMapping("/lookup/major-category")
    public CatalogResponseDTO<?> lookupMajorCategory(@RequestParam String name,
                                                     @RequestParam(required = false) String educationLevel) {
        return catalogService.lookupMajorCategory(name, educationLevel);
    }

    @GetMapping("/lookup/major-discipline")
    public CatalogResponseDTO<?> lookupMajorDiscipline(@RequestParam String name,
                                                       @RequestParam(required = false) String educationLevel) {
        return catalogService.lookupMajorDiscipline(name, educationLevel);
    }

    @GetMapping("/lookup/province")
    public CatalogResponseDTO<?> lookupProvince(@RequestParam String name) {
        return catalogService.lookupProvince(name);
    }

    @GetMapping("/lookup/city")
    public CatalogResponseDTO<?> lookupCity(@RequestParam String name) {
        return catalogService.lookupCity(name);
    }

    @GetMapping("/search/school")
    public CatalogResponseDTO<?> searchSchools(@RequestParam String keyword) {
        return catalogService.searchSchools(keyword);
    }

    @GetMapping("/search/major")
    public CatalogResponseDTO<?> searchMajors(@RequestParam String keyword,
                                              @RequestParam(required = false) String educationLevel) {
        return catalogService.searchMajors(keyword, educationLevel);
    }

    @GetMapping("/tree/major")
    public CatalogResponseDTO<List<CatalogMajorTreeNodeDTO>> getMajorTree(
            @RequestParam(required = false) String educationLevel) {
        return catalogService.getMajorTree(educationLevel);
    }

    @GetMapping("/tree/region")
    public CatalogResponseDTO<List<CatalogRegionTreeNodeDTO>> getRegionTree() {
        return catalogService.getRegionTree();
    }

    @GetMapping("/tree/filter-tags")
    public CatalogResponseDTO<CatalogFilterTagsTreeDTO> getFilterTagsTree() {
        return catalogService.getFilterTagsTree();
    }
}
