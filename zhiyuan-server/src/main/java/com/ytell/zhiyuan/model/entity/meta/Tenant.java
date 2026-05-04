package com.ytell.zhiyuan.model.entity.meta;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;


@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@TableName("assistant_tenant_info")
public class Tenant {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String companyName;
    private String companyBusiness;
    private String tagList;
    private Date createTime;
    private Date updateTime;

}
