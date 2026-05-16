package com.ytell.zhiyuan.web.controller.admin;

import cn.hutool.core.date.DateUtil;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.UserCredentialMapper;
import com.ytell.zhiyuan.mapper.UserMapper;
import com.ytell.zhiyuan.model.dto.gaotu.res.UserRightsByUserIdRes;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.LoginType;
import com.ytell.zhiyuan.model.enums.UserLevel;
import com.ytell.zhiyuan.model.req.AddUserRequest;
import com.ytell.zhiyuan.model.vo.UserVO;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.biz.UserBizService;
import io.swagger.annotations.Api;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.Date;
import java.util.UUID;

@Slf4j
@RestController
@RequestMapping("/gaotu-assistant-bot/admin/user/")
@Api(tags = "后台管理接口")

public class UserAdminController {

    @Autowired
    private UserMapper userMapper;
    @Autowired
    private UserCredentialMapper userCredentialMapper;

    @Autowired
    private UserBizService userBizService;

    @Autowired
    private GaotuService gaotuService;

    @PostMapping("/add-user")
    public Boolean addUser(@RequestBody AddUserRequest request) {
//
        User user = new User();
        user.setTenantId(request.getTenantId());
        user.setBotId(request.getBotId());
        user.setIsCustomer(false);
        user.setChannel("ytell");
        // 设置B端用户的默认限制（更高的限制）
        user.setLimitSettings(userBizService.generateDefaultLimitSettings(false, "ytell", UserLevel.SUPER_VIP));
        userMapper.insert(user);
//
        UserCredential userCredential = new UserCredential();
        userCredential.setUserId(user.getId());
        userCredential.setIdentifier(request.getUserName());
        userCredential.setPasswordHash(request.getPassword());
        userCredential.setLoginToken(UUID.randomUUID().toString());
        userCredential.setLoginType(LoginType.USERNAME);
        userCredentialMapper.insert(userCredential);
        return Boolean.TRUE;
    }

    @PostMapping("/update-user-level")
    public Boolean updateUserLevel(@RequestParam("userId") Long userId,
                                   @RequestParam("channel") String channel,
                                   @RequestParam("userLevel") UserLevel userLevel,
                                   @RequestParam(value = "expiredDate", required = false) String expiredDate) {
        userBizService.updateUserLevel(userId, channel, userLevel, expiredDate != null ? DateUtil.parseDate(expiredDate) : null);
        return Boolean.TRUE;
    }

    @GetMapping("/gaotu-user")
    public UserVO getGaotuUser(@RequestParam("memberId") String memberId,
                               @RequestParam(value = "channel", defaultValue = "gaotu") String channel) {
        UserCredential userCredential = getGaotuUserCredential(memberId, channel);
        UserVO userVO = userBizService.getUserVoById(userCredential.getUserId());
        if (userVO == null) {
            throw new BusinessException(110, "未找到高途用户对应的本地用户，memberId=" + memberId + ", channel=" + channel);
        }
        return userVO;
    }

    @PostMapping("/update-gaotu-user-level")
    public Boolean updateGaotuUserLevel(@RequestParam("memberId") String memberId,
                                        @RequestParam(value = "channel", defaultValue = "gaotu") String channel,
                                        @RequestParam("userLevel") UserLevel userLevel,
                                        @RequestParam(value = "expiredDate", required = false) String expiredDate) {
        UserCredential userCredential = getGaotuUserCredential(memberId, channel);
        userBizService.updateUserLevel(
                userCredential.getUserId(),
                channel,
                userLevel,
                expiredDate != null ? DateUtil.parseDate(expiredDate) : null
        );
        return Boolean.TRUE;
    }

    @PostMapping("/fix-gaotu-user-level")
    public Boolean fixUserLevel(@RequestParam("memberId") String memberId,
                                @RequestParam(value = "channel", defaultValue = "gaotu") String channel) {

        UserRightsByUserIdRes userRightsByUserIdRes= gaotuService.getUserRights(memberId);
        Integer userType = userRightsByUserIdRes.getUserType();
        Date expiredDate = userRightsByUserIdRes.getExpirationTime();
        UserLevel userLevel = UserLevel.convertGaotuLevel(userType);
        UserCredential userCredential = getGaotuUserCredential(memberId, channel);
        userBizService.updateUserLevel(userCredential.getUserId(), channel, userLevel, expiredDate);
        return Boolean.TRUE;
    }

    private UserCredential getGaotuUserCredential(String memberId, String channel) {
        QueryWrapper<UserCredential> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(UserCredential::getIdentifier, memberId);
        queryWrapper.lambda().eq(UserCredential::getLoginType, LoginType.TOKEN);
        queryWrapper.lambda().eq(UserCredential::getChannel, channel);
        UserCredential userCredential = userCredentialMapper.selectOne(queryWrapper);
        if (userCredential == null) {
            throw new BusinessException(110, "未找到高途用户，memberId=" + memberId + ", channel=" + channel);
        }
        return userCredential;
    }

}
