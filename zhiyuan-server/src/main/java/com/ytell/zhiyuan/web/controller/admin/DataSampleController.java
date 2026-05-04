package com.ytell.zhiyuan.web.controller.admin;

import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.service.biz.ChatSessionBizService;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/gaotu-assistant-bot/admin/data-sample")
@Api(tags = "后台管理接口")

public class DataSampleController {

    @Autowired
    private ChatSessionBizService chatSessionBizService;

    @GetMapping("/volunteer")
    public List<VolunteerSchoolGroup> addUser(@RequestParam("chatSessionId")Long chatSessionId) {
        return chatSessionBizService.loadSessionVolunteerFormatData(chatSessionId);
    }

}
