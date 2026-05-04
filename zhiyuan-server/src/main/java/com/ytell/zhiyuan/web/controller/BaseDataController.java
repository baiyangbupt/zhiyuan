package com.ytell.zhiyuan.web.controller;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.manager.EthnicityManager;
import com.ytell.zhiyuan.manager.MajorMappingManager;
import com.ytell.zhiyuan.manager.ProvinceCityManager;
import com.ytell.zhiyuan.manager.UnacceptableMajorManager;
import com.ytell.zhiyuan.manager.ali.AliOSSService;
import com.ytell.zhiyuan.model.dto.MajorInfo;
import com.ytell.zhiyuan.model.dto.gaotu.req.ScorePositionRangeReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import com.ytell.zhiyuan.model.req.UnAcceptableMajorsReq;
import com.ytell.zhiyuan.model.vo.EthnicityVO;
import com.ytell.zhiyuan.model.vo.ProvinceCityVO;
import com.ytell.zhiyuan.model.vo.RegionProvinceVO;
import com.ytell.zhiyuan.model.vo.UnacceptableMajorVO;
import com.ytell.zhiyuan.service.GaotuService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/gaotu-assistant-bot/base-data/")
@Api(tags = "基础信息获取接口")
public class BaseDataController {

    @Autowired
    private GaotuService gaotuService;
    @Autowired
    private ProvinceCityManager provinceCityManager;

    @Autowired
    private MajorMappingManager majorMappingManager;

    @Autowired
    private EthnicityManager ethnicityManager;

    @Autowired
    private UnacceptableMajorManager unacceptableMajorManager;

    @Autowired
    private AliOSSService aliOSSService;


    @GetMapping("/province-city")
    @ApiOperation("获取省市数据")
    public BaseResponse<List<ProvinceCityVO>> getProvinceCity() {
        return BaseResponse.success(provinceCityManager.getAllProvinces());
    }

    @GetMapping("/major-level2-data")
    @ApiOperation("获取专业数据")
    public BaseResponse<List<MajorInfo>> getTwoLevelAllMajors(@RequestParam("educationLevel") MajorMappingManager.EducationLevel educationLevel) {
        return BaseResponse.success(majorMappingManager.getTwoLevelAllMajors(educationLevel));
    }


    @PostMapping("/score/position-range")
    @ApiOperation("根据分数获取位次范围")
    public BaseResponse<ScorePositionRangeRes> getScorePositionRange(@RequestBody ScorePositionRangeReq req) {
        return BaseResponse.success(gaotuService.getScorePositionRange(req));
    }

    @GetMapping("/region-province")
    @ApiOperation("获取按大区分组的省份列表")
    public BaseResponse<List<RegionProvinceVO>> getRegionProvinceList() {
        return BaseResponse.success(provinceCityManager.getRegionProvinceList());
    }

    @GetMapping("/ethnicity-list")
    @ApiOperation("获取民族列表")
    public BaseResponse<List<EthnicityVO>> getEthnicityList() {
        return BaseResponse.success(ethnicityManager.getAllEthnicities());
    }

    @PostMapping("/unacceptable-majors")
    @ApiOperation("获取不能接受的专业列表")
    public BaseResponse<List<UnacceptableMajorVO>> getUnacceptableMajors(@RequestBody UnAcceptableMajorsReq req) {
        return BaseResponse.success(unacceptableMajorManager.getByReq(req));
    }

    @GetMapping("/get-oss-sign")
    @ApiOperation("获取oss上传文件的签名")
    public BaseResponse<Map<String, String>> getOSSSignature(@RequestParam(value = "dir",defaultValue = "user") String dir) {
        return BaseResponse.success(aliOSSService.getSignature(dir));
    }

}