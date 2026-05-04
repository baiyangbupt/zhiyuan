package com.ytell.zhiyuan.web.controller.inner;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.manager.MajorProfileManager;
import com.ytell.zhiyuan.model.dto.MajorProfileDto;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/gaotu-assistant-bot/inner/major")
@Api(tags = "内部使用接口")
public class MajorProfileController {

    @Autowired
    private MajorProfileManager majorProfileManager;

    @GetMapping("/getMajorProfile")
    public MajorProfileDto getMajorProfileByName(@RequestParam(value = "name", required = false) String name,
                                                 @RequestParam(value = "id", required = false) String id) {
        MajorProfileDto res = null;

        if (!Strings.isNullOrEmpty(id)) {
            res = majorProfileManager.getMajorProfileById(id);
        }
        if (!Strings.isNullOrEmpty(name) && res == null) {
            res = majorProfileManager.getMajorProfileByName(name);
        }
        return res;
    }
}
