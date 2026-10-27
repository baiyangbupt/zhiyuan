package com.ytell.zhiyuan.common.util;

import com.alibaba.excel.annotation.ExcelProperty;
import com.alibaba.excel.annotation.write.style.ColumnWidth;
import com.alibaba.excel.annotation.write.style.HeadRowHeight;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.time.DateUtils;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.ss.util.CellRangeAddress;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;

import java.io.ByteArrayOutputStream;
import java.util.*;

/**
 * Excel工具类
 */
@Slf4j
public class ExcelUtil {

    /**
     * 生成志愿列表Excel文件
     *
     * @param userScoreDetail 用户分数详情
     * @param mainData 主列表志愿数据
     * @param backupData 候补列表志愿数据
     * @param multiMajor 是否专业组模式
     * @return Excel文件的字节数组
     */
    public static byte[] generateVolunteerExcel(CreateSessionReq userScoreDetail, List<VolunteerExcelData> mainData, List<VolunteerExcelData> backupData, boolean multiMajor) {
        return generateVolunteerExcel(userScoreDetail, mainData, backupData, multiMajor, null);
    }

    public static byte[] generateVolunteerExcel(CreateSessionReq userScoreDetail, List<VolunteerExcelData> mainData,
                                               List<VolunteerExcelData> backupData, boolean multiMajor,
                                               String note) {
        try (ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
             Workbook workbook = new XSSFWorkbook()) {

            Sheet sheet = workbook.createSheet("志愿列表");

            // 创建样式
            CellStyle headerStyle = createHeaderStyle(workbook);
            CellStyle subHeaderStyle = createSubHeaderStyle(workbook);
            CellStyle dataStyle = createDataStyle(workbook);
            CellStyle separatorStyle = createSeparatorStyle(workbook); // 分隔行样式

            int rowIndex = 0;
            int year = DateUtils.toCalendar(new Date()).get(Calendar.YEAR);

            // 第一行：省份、分数、选科 + 下载时间
            rowIndex = createDownloadTimeRow(sheet, rowIndex, headerStyle, multiMajor, userScoreDetail);

            // 可选警告行：草案/冲突/审查暂停必须在导出件里可见，不能只藏在卡片里。
            if (note != null && !note.trim().isEmpty()) {
                Row noteRow = sheet.createRow(rowIndex++);
                Cell noteCell = noteRow.createCell(0);
                noteCell.setCellValue(note.trim());
                CellStyle noteStyle = workbook.createCellStyle();
                noteStyle.setWrapText(true);
                Font noteFont = workbook.createFont();
                noteFont.setBold(true);
                noteFont.setColor(IndexedColors.RED.getIndex());
                noteStyle.setFont(noteFont);
                noteCell.setCellStyle(noteStyle);
                sheet.addMergedRegion(new CellRangeAddress(noteRow.getRowNum(), noteRow.getRowNum(), 0, 8));
            }

            // 第二行：年份分组表头
            rowIndex = createYearGroupHeaderRow(sheet, rowIndex, subHeaderStyle, year, multiMajor);

            // 第三行：详细字段表头
            rowIndex = createDetailHeaderRow(sheet, rowIndex, subHeaderStyle, multiMajor);

            // 主列表数据行
            int mainDataEndRow = createDataRows(sheet, rowIndex, mainData, dataStyle, multiMajor);

            // 如果有候补数据，添加分隔行
            if (backupData != null && !backupData.isEmpty()) {
                rowIndex = mainDataEndRow;
                rowIndex = createSeparatorRow(sheet, rowIndex, separatorStyle, multiMajor);
                
                // 候补列表数据行
                createDataRows(sheet, rowIndex, backupData, dataStyle, multiMajor);
            }

            // 设置列宽
            setColumnWidths(sheet, multiMajor);

            workbook.write(outputStream);
            return outputStream.toByteArray();

        } catch (Exception e) {
            log.error("生成Excel文件失败", e);
            throw new RuntimeException("生成Excel文件失败", e);
        }
    }

    /**
     * 创建表头样式
     */
    private static CellStyle createHeaderStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setFillForegroundColor(IndexedColors.GREY_25_PERCENT.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        style.setBorderTop(BorderStyle.THIN);
        style.setBorderBottom(BorderStyle.THIN);
        style.setBorderLeft(BorderStyle.THIN);
        style.setBorderRight(BorderStyle.THIN);

        Font font = workbook.createFont();
        font.setBold(true);
        font.setFontHeightInPoints((short) 12);
        style.setFont(font);

        return style;
    }

    /**
     * 创建子表头样式
     */
    private static CellStyle createSubHeaderStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setFillForegroundColor(IndexedColors.LIGHT_CORNFLOWER_BLUE.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        style.setBorderTop(BorderStyle.THIN);
        style.setBorderBottom(BorderStyle.THIN);
        style.setBorderLeft(BorderStyle.THIN);
        style.setBorderRight(BorderStyle.THIN);

        Font font = workbook.createFont();
        font.setBold(true);
        font.setFontHeightInPoints((short) 10);
        style.setFont(font);

        return style;
    }

    /**
     * 创建数据样式
     */
    private static CellStyle createDataStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        style.setBorderTop(BorderStyle.THIN);
        style.setBorderBottom(BorderStyle.THIN);
        style.setBorderLeft(BorderStyle.THIN);
        style.setBorderRight(BorderStyle.THIN);

        Font font = workbook.createFont();
        font.setFontHeightInPoints((short) 10);
        style.setFont(font);

        return style;
    }

    /**
     * 创建分隔行样式
     */
    private static CellStyle createSeparatorStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setFillForegroundColor(IndexedColors.YELLOW.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        style.setBorderTop(BorderStyle.THIN);
        style.setBorderBottom(BorderStyle.THIN);
        style.setBorderLeft(BorderStyle.THIN);
        style.setBorderRight(BorderStyle.THIN);

        Font font = workbook.createFont();
        font.setBold(true);
        font.setFontHeightInPoints((short) 12);
        font.setColor(IndexedColors.DARK_BLUE.getIndex());
        style.setFont(font);

        return style;
    }

    /**
     * 创建分隔行
     * @return 下一行的索引
     */
    private static int createSeparatorRow(Sheet sheet, int rowIndex, CellStyle style, boolean multiMajor) {
        Row row = sheet.createRow(rowIndex);
        row.setHeight((short) 500);

        Cell cell = row.createCell(0);
        cell.setCellValue("候补志愿");
        cell.setCellStyle(style);

        // 根据模式决定合并范围
        int lastColumn = multiMajor ? 24 : 23; // 专业组模式多一列专业录取概率
        sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 0, lastColumn));

        return rowIndex + 1;
    }

    /**
     * 创建下载时间行（包含省份、分数、选科信息）
     */
    private static int createDownloadTimeRow(Sheet sheet, int rowIndex, CellStyle style, boolean multiMajor, CreateSessionReq userScoreDetail) {
        Row row = sheet.createRow(rowIndex);
        row.setHeight((short) 600); // 设置行高

        // 构建左侧信息：省份、分数、选科
        List<String> leftParts = new ArrayList<>();
        
        // 省份
        if (userScoreDetail.getProvince() != null && userScoreDetail.getProvince().getName() != null) {
            leftParts.add("省份：" + userScoreDetail.getProvince().getName());
        }
        
        // 分数
        if (userScoreDetail.getTotalScore() != null) {
            leftParts.add("分数：" + userScoreDetail.getTotalScore() + "分");
        }
        
        // 选科
        String subjectStr = getSubjectString(userScoreDetail);
        if (subjectStr != null && !subjectStr.isEmpty()) {
            leftParts.add("选科：" + subjectStr);
        }
        
        String leftInfo = String.join("  ", leftParts);
        
        // 右侧：下载时间
        String downloadTime = "下载时间：" + java.time.LocalDateTime.now()
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyy年MM月dd日 HH:mm"));
        
        // 左侧单元格：省份、分数、选科
        Cell leftCell = row.createCell(0);
        leftCell.setCellValue(leftInfo);
        leftCell.setCellStyle(style);
        
        // 右侧单元格：下载时间
        int lastColumn = multiMajor ? 24 : 23; // 专业组模式多一列专业录取概率
        // 计算右侧起始列（大约在中间位置，或者根据内容长度调整）
        int rightStartCol = Math.max(10, lastColumn / 2); // 至少从第10列开始，或者中间位置
        
        Cell rightCell = row.createCell(rightStartCol);
        rightCell.setCellValue(downloadTime);
        rightCell.setCellStyle(style);
        
        // 合并左侧区域（从0到rightStartCol-1）
        if (rightStartCol > 0) {
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 0, rightStartCol - 1));
        }
        
        // 合并右侧区域（从rightStartCol到lastColumn）
        sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, rightStartCol, lastColumn));

        return rowIndex + 1;
    }

    /**
     * 获取选科字符串
     */
    private static String getSubjectString(CreateSessionReq userScoreDetail) {
        if (userScoreDetail.getSubjectList() != null && !userScoreDetail.getSubjectList().isEmpty()) {
            List<String> subjectFobiddenList = Arrays.asList("08", "10", "11");
            List<String> subjects = userScoreDetail.getSubjectList().stream()
                    .filter(subject -> !subjectFobiddenList.contains(subject.getValue()))
                    .map(subject -> subject.getName())
                    .collect(java.util.stream.Collectors.toList());
            if (!subjects.isEmpty()) {
                return String.join(".", subjects);
            }
        }
        // 如果没有科目列表，使用科目类型
        if (userScoreDetail.getSubjectType() != null && userScoreDetail.getSubjectType().getDesc() != null) {
            return userScoreDetail.getSubjectType().getDesc();
        }
        return "";
    }

    /**
     * 创建年份分组表头行
     */
    private static int createYearGroupHeaderRow(Sheet sheet, int rowIndex, CellStyle style, int year, boolean multiMajor) {
        Row row = sheet.createRow(rowIndex);
        row.setHeight((short) 500);

        if (multiMajor) {
            // 专业组模式：增加专业录取概率列
            // 第一年(招生计划) - A到P列 (0-15)
            Cell cell1 = row.createCell(0);
            cell1.setCellValue(year + "年(招生计划)");
            cell1.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 0, 15));

            // 第二年 - Q到S列 (16-18)
            Cell cell2 = row.createCell(16);
            cell2.setCellValue(String.valueOf(year - 1));
            cell2.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 16, 18));

            // 第三年 - T到V列 (19-21)
            Cell cell3 = row.createCell(19);
            cell3.setCellValue(String.valueOf(year - 2));
            cell3.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 19, 21));

            // 第四年 - W到Y列 (22-24)
            Cell cell4 = row.createCell(22);
            cell4.setCellValue(String.valueOf(year - 3));
            cell4.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 22, 24));
        } else {
            // 学校+专业模式：原有逻辑
            // 第一年(招生计划) - A到O列 (0-14)
            Cell cell1 = row.createCell(0);
            cell1.setCellValue(year + "年(招生计划)");
            cell1.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 0, 14));

            // 第二年 - P到R列 (15-17)
            Cell cell2 = row.createCell(15);
            cell2.setCellValue(String.valueOf(year - 1));
            cell2.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 15, 17));

            // 第三年 - S到U列 (18-20)
            Cell cell3 = row.createCell(18);
            cell3.setCellValue(String.valueOf(year - 2));
            cell3.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 18, 20));

            // 第四年 - V到X列 (21-23)
            Cell cell4 = row.createCell(21);
            cell4.setCellValue(String.valueOf(year - 3));
            cell4.setCellStyle(style);
            sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex, 21, 23));
        }

        return rowIndex + 1;
    }

    /**
     * 创建详细字段表头行
     */
    private static int createDetailHeaderRow(Sheet sheet, int rowIndex, CellStyle style, boolean multiMajor) {
        Row row = sheet.createRow(rowIndex);
        row.setHeight((short) 500);

        if (multiMajor) {
            // 专业组模式：增加专业录取概率列
            String[] currentYearHeaders = {
                    "序号", "录取概率", "院校代码", "院校", "层次", "地区/城市", "类型", "性质",
                    "排名", "专业录取概率", "专业代码", "专业", "计划", "学费", "学制", "选科"
            };

            for (int i = 0; i < currentYearHeaders.length; i++) {
                Cell cell = row.createCell(i);
                cell.setCellValue(currentYearHeaders[i]);
                cell.setCellStyle(style);
            }

            // 历史年份的字段表头 (2024, 2023, 2022)
            String[] historyHeaders = {"录取人数", "最低分", "最低位次"};

            // 为三个历史年份分别创建字段表头
            for (int year = 0; year < 3; year++) {
                int startCol = 16 + year * 3; // 2024年从第16列开始，每3列一组
                for (int j = 0; j < historyHeaders.length; j++) {
                    Cell cell = row.createCell(startCol + j);
                    cell.setCellValue(historyHeaders[j]);
                    cell.setCellStyle(style);
                }
            }
        } else {
            // 学校+专业模式：原有逻辑
            String[] currentYearHeaders = {
                    "序号", "录取概率", "院校代码", "院校", "层次", "地区/城市", "类型", "性质",
                    "排名", "专业代码", "专业", "计划", "学费", "学制", "选科"
            };

            for (int i = 0; i < currentYearHeaders.length; i++) {
                Cell cell = row.createCell(i);
                cell.setCellValue(currentYearHeaders[i]);
                cell.setCellStyle(style);
            }

            // 历史年份的字段表头 (2024, 2023, 2022)
            String[] historyHeaders = {"录取人数", "最低分", "最低位次"};

            // 为三个历史年份分别创建字段表头
            for (int year = 0; year < 3; year++) {
                int startCol = 15 + year * 3; // 2024年从第15列开始，每3列一组
                for (int j = 0; j < historyHeaders.length; j++) {
                    Cell cell = row.createCell(startCol + j);
                    cell.setCellValue(historyHeaders[j]);
                    cell.setCellStyle(style);
                }
            }
        }

        return rowIndex + 1;
    }

    /**
     * 创建数据行
     * @return 结束的行索引（下一行的索引）
     */
    private static int createDataRows(Sheet sheet, int startRowIndex, List<VolunteerExcelData> volunteerData, CellStyle style, boolean multiMajor) {
        int currentRowIndex = startRowIndex;

        for (VolunteerExcelData data : volunteerData) {
            List<VolunteerMajorExcelData> majorList = data.getMajorList();
            if (majorList == null || majorList.isEmpty()) {
                continue;
            }

            int schoolStartRow = currentRowIndex;
            int majorCount = majorList.size();

            // 为每个专业创建一行
            for (int j = 0; j < majorCount; j++) {
                VolunteerMajorExcelData majorData = majorList.get(j);
                Row row = sheet.createRow(currentRowIndex);
                row.setHeight((short) 400);

                // 学校信息只在第一行填写，后续行留空（稍后会被合并）
                if (j == 0) {
                    // 使用数据中已设置的序号
                    setCellValue(row, 0, data.getIndex() != null ? data.getIndex() : "", style); // 序号
                    setCellValue(row, 1, data.getEnrollRatio()+"%", style);
                    setCellValue(row, 2, data.getSchoolCode(), style);
                    setCellValue(row, 3, data.getSchoolName(), style);
                    setCellValue(row, 4, data.getSchoolLevel(), style);
                    setCellValue(row, 5, data.getSchoolPosition(), style);
                    setCellValue(row, 6, data.getSchoolType(), style);
                    setCellValue(row, 7, data.getSchoolNature(), style);
                    setCellValue(row, 8, data.getSchoolRank(), style);
                } else {
                    // 其他行的学校信息列创建空单元格（样式保持一致）
                    for (int col = 0; col <= 8; col++) {
                        setCellValue(row, col, "", style);
                    }
                }

                if (multiMajor) {
                    // 专业组模式：增加专业录取概率列
                    setCellValue(row, 9, majorData.getMajorEnrollRatio(), style);
                    setCellValue(row, 10, majorData.getMajorCode(), style);
                    setCellValue(row, 11, majorData.getMajorName(), style);
                    setCellValue(row, 12, majorData.getMajorPlan(), style);
                    setCellValue(row, 13, majorData.getMajorTuition(), style);
                    setCellValue(row, 14, majorData.getMajorDuration(), style);
                    setCellValue(row, 15, majorData.getMajorSelectInfo(), style);

                    setCellValue(row, 16, majorData.getMajorEnrollNumLastYear(), style);
                    setCellValue(row, 17, majorData.getMajorMinScoreLastYear(), style);
                    setCellValue(row, 18, majorData.getMajorMinPosLastYear(), style);

                    setCellValue(row, 19, majorData.getMajorEnrollNumYearBefore(), style);
                    setCellValue(row, 20, majorData.getMajorMinScoreYearBefore(), style);
                    setCellValue(row, 21, majorData.getMajorMinPosYearBefore(), style);

                    setCellValue(row, 22, majorData.getMajorEnrollNumYearBeforeLast(), style);
                    setCellValue(row, 23, majorData.getMajorMinScoreYearBeforeLast(), style);
                    setCellValue(row, 24, majorData.getMajorMinPosYearBeforeLast(), style);
                } else {
                    // 学校+专业模式：原有逻辑
                    setCellValue(row, 9, majorData.getMajorCode(), style);
                    setCellValue(row, 10, majorData.getMajorName(), style);
                    setCellValue(row, 11, majorData.getMajorPlan(), style);
                    setCellValue(row, 12, majorData.getMajorTuition(), style);
                    setCellValue(row, 13, majorData.getMajorDuration(), style);
                    setCellValue(row, 14, majorData.getMajorSelectInfo(), style);

                    setCellValue(row, 15, majorData.getMajorEnrollNumLastYear(), style);
                    setCellValue(row, 16, majorData.getMajorMinScoreLastYear(), style);
                    setCellValue(row, 17, majorData.getMajorMinPosLastYear(), style);

                    setCellValue(row, 18, majorData.getMajorEnrollNumYearBefore(), style);
                    setCellValue(row, 19, majorData.getMajorMinScoreYearBefore(), style);
                    setCellValue(row, 20, majorData.getMajorMinPosYearBefore(), style);

                    setCellValue(row, 21, majorData.getMajorEnrollNumYearBeforeLast(), style);
                    setCellValue(row, 22, majorData.getMajorMinScoreYearBeforeLast(), style);
                    setCellValue(row, 23, majorData.getMajorMinPosYearBeforeLast(), style);
                }

                currentRowIndex++;
            }

            // 如果该学校有多个专业，合并学校信息的单元格
            if (majorCount > 1) {
                int schoolEndRow = currentRowIndex - 1;
                // 合并学校信息列 (序号到排名：0-8列)
                for (int col = 0; col <= 8; col++) {
                    sheet.addMergedRegion(new CellRangeAddress(schoolStartRow, schoolEndRow, col, col));
                }
            }
        }
        
        return currentRowIndex;
    }

    /**
     * 设置单元格值
     */
    private static void setCellValue(Row row, int columnIndex, Object value, CellStyle style) {
        Cell cell = row.createCell(columnIndex);
        if (value != null) {
            if (value instanceof Number) {
                cell.setCellValue(((Number) value).doubleValue());
            } else {
                cell.setCellValue(value.toString());
            }
        } else {
            cell.setCellValue("");
        }
        cell.setCellStyle(style);
    }

    /**
     * 设置列宽
     */
    private static void setColumnWidths(Sheet sheet, boolean multiMajor) {
        if (multiMajor) {
            // 专业组模式：增加专业录取概率列
            int[] columnWidths = {
                    8, 12, 12, 25, 25, 12, 12, 12, 12, 12, 12, 50, 12, 12, 12, 12, // 2025年字段(16列)
                    12, 12, 12,
                    12, 12, 12,
                    12, 12, 12
            };

            for (int i = 0; i < columnWidths.length; i++) {
                sheet.setColumnWidth(i, columnWidths[i] * 256);
            }
        } else {
            // 学校+专业模式：原有逻辑
            int[] columnWidths = {
                    8, 12, 12, 25, 25, 12, 12, 12, 12, 12, 50, 12, 12, 12, 12, // 2025年字段(15列)
                    12, 12, 12,
                    12, 12, 12,
                    12, 12, 12
            };

            for (int i = 0; i < columnWidths.length; i++) {
                sheet.setColumnWidth(i, columnWidths[i] * 256);
            }
        }
    }

    /**
     * 志愿Excel数据模型
     */
    @Data
    @HeadRowHeight(25)
    public static class VolunteerExcelData {

        // 上层表头合并单元格，上层表头名称：{thisyear}年(招生计划)
        @ExcelProperty(value = "序号", index = 0)
        @ColumnWidth(8)
        private Integer index;

        @ExcelProperty(value = "录取概率", index = 1)
        @ColumnWidth(12)
        private String enrollRatio;

        @ExcelProperty(value = "院校代码", index = 2)
        @ColumnWidth(12)
        private String schoolCode;

        @ExcelProperty(value = "院校", index = 3)
        @ColumnWidth(25)
        private String schoolName;

        @ExcelProperty(value = "层次", index = 4)
        @ColumnWidth(25)
        private String schoolLevel;

        @ExcelProperty(value = "地区/城市", index = 5)
        @ColumnWidth(12)
        private String schoolPosition;

        @ExcelProperty(value = "类型", index = 6)
        @ColumnWidth(12)
        private String schoolType; 

        @ExcelProperty(value = "性质", index = 7)
        @ColumnWidth(12)
        private String schoolNature;

        @ExcelProperty(value = "排名", index = 8)
        @ColumnWidth(12)
        private String schoolRank;

        private List<VolunteerMajorExcelData> majorList;
    }

    @Data
    @HeadRowHeight(25)
    public static class VolunteerMajorExcelData {
        @ExcelProperty(value = "专业录取概率", index = 9)
        @ColumnWidth(12)
        private String majorEnrollRatio;

        @ExcelProperty(value = "专业代码", index = 9)
        @ColumnWidth(12)
        private String majorCode;

        @ExcelProperty(value = "专业", index = 10)
        @ColumnWidth(25)
        private String majorName;

        @ExcelProperty(value = "计划", index = 11)
        @ColumnWidth(12)
        private String majorPlan;

        @ExcelProperty(value = "学费", index = 12)
        @ColumnWidth(12)
        private String majorTuition;

        @ExcelProperty(value = "学制", index = 13)
        @ColumnWidth(12)
        private String majorDuration;


        @ExcelProperty(value = "选科", index = 14)
        @ColumnWidth(12)
        private String majorSelectInfo;

        //{thisyear}年(招生计划) end

        // 上层表头合并单元格， 上层表头名称：{thisyear-1}
        @ExcelProperty(value = "录取人数", index = 15)
        @ColumnWidth(12)
        private String majorEnrollNumLastYear;
        @ExcelProperty(value = "最低分", index = 16)
        @ColumnWidth(12)
        private String majorMinScoreLastYear;
        @ExcelProperty(value = "最低位次", index = 17)
        @ColumnWidth(12)
        private String majorMinPosLastYear;
        // {thisyear-1} end

        // 上层表头合并单元格， 上层表头名称：{thisyear-2}
        @ExcelProperty(value = "录取人数", index = 18)
        @ColumnWidth(12)
        private String majorEnrollNumYearBefore;
        @ExcelProperty(value = "最低分", index = 19)
        @ColumnWidth(12)
        private String majorMinScoreYearBefore;
        @ExcelProperty(value = "最低位次", index = 20)
        @ColumnWidth(12)
        private String majorMinPosYearBefore;
        // {thisyear-2} end

        // 上层表头合并单元格， 上层表头名称：{thisyear-3}
        @ExcelProperty(value = "录取人数", index = 21)
        @ColumnWidth(12)
        private String majorEnrollNumYearBeforeLast;
        @ExcelProperty(value = "最低分", index = 22)
        @ColumnWidth(12)
        private String majorMinScoreYearBeforeLast;
        @ExcelProperty(value = "最低位次", index = 23)
        @ColumnWidth(12)
        private String majorMinPosYearBeforeLast;
        // {thisyear-3} end
    }
}
