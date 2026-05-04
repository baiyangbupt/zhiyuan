package com.ytell.zhiyuan.model.dto.gaotu.res;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import lombok.Data;

import java.util.List;
import java.util.stream.Collectors;

@Data
public class UserInfoByTokenRes {
    private String userName; // 用户姓名
    private String avatar; // 用户头像
    private String memberId; // 用户id
    private String source; //"B"--B端，"C"--C端
    private String examYear; // 高考年份
    private ProvinceInfo province; // 高考省份
    private SexInfo sex; // 性别
    private SubjectTypeInfo subjectType; // 科目类型
    private List<SubjectItemInfo> subjectList; // 科目列表

    @Data
    public static class ProvinceInfo {
        private String key; // 省份代码
        private String data; // 省份名称
    }

    @Data
    public static class SexInfo {
        private String code; // 性别代码
        private String desc; // 性别描述
    }

    @Data
    public static class SubjectTypeInfo {
        private String code; // 科目类型代码
        private String desc; // 科目类型描述
    }

    @Data
    public static class SubjectItemInfo {
        private Boolean isFirst; // 是否首选
        private String name; // 科目名称
        private String code; // 科目代码
    }

    /**
     * 转换为系统内部的CreateSessionReq格式
     *
     * @return CreateSessionReq对象
     */
    public CreateSessionReq toCreateSessionReq() {
        CreateSessionReq req = new CreateSessionReq();

        // 基本信息
        req.setUserName(this.userName);
        req.setExamYear(this.examYear != null ? Integer.valueOf(this.examYear) : null);

        // 省份信息转换
        if (this.province != null) {
            CreateSessionReq.Province province = new CreateSessionReq.Province();
            province.setCode(this.province.getKey());
            province.setName(this.province.getData());
            req.setProvince(province);
        }

//        // 性别信息转换
//        if (this.sex != null) {
//            CreateSessionReq.Sex sex = new CreateSessionReq.Sex();
//            sex.setCode(this.sex.getCode());
//            sex.setName(this.sex.getDesc());
//            req.setSex(sex);
//        }

        // 科目类型转换
        if (this.subjectType != null) {
            CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
            subjectType.setCode(this.subjectType.getCode());
            subjectType.setDesc(this.subjectType.getDesc());
            req.setSubjectType(subjectType);
        }

        // 科目列表转换
        if (this.subjectList != null) {
            List<CreateSessionReq.SubjectItem> subjectItems = this.subjectList.stream()
                    .map(this::convertSubjectItem)
                    .collect(Collectors.toList());
            req.setSubjectList(subjectItems);
        }

        return req;
    }

    /**
     * 转换单个科目项
     */
    private CreateSessionReq.SubjectItem convertSubjectItem(SubjectItemInfo item) {
        return new CreateSessionReq.SubjectItem(
                item.getIsFirst() ? 1 : 0,
                item.getCode(),
                item.getCode(),
                item.getName()
        );
    }
}
