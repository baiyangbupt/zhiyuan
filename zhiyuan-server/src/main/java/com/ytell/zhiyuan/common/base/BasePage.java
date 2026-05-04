package com.ytell.zhiyuan.common.base;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.Data;

import java.util.List;

@Data
public class BasePage<T> {

    /**
     * 当前页码
     */
    private long current;

    /**
     * 总记录数
     */
    private long total;

    /**
     * 查询结果
     */
    private List<T> records;

    public static <T> BasePage<T> wrapper(long current, long total, List<T> records) {
        BasePage basePage = new BasePage();
        basePage.setTotal(total);
        basePage.setCurrent(current);
        basePage.setRecords(records);
        return basePage;
    }

    public static <T> BasePage<T> parse(Page<T> page) {
        BasePage basePage = new BasePage();
        basePage.setTotal(page.getTotal());
        basePage.setCurrent(page.getCurrent());
        basePage.setRecords(page.getRecords());
        return basePage;
    }

}
