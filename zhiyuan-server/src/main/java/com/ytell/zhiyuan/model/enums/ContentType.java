package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import com.google.common.collect.Lists;
import lombok.AllArgsConstructor;
import lombok.Getter;

import java.util.Arrays;
import java.util.List;

@Getter
@AllArgsConstructor
public enum ContentType {

    TEXT(0, "text", Lists.newArrayList()),
    IMAGE(1, "image", Lists.newArrayList("png", "jpg", "jpeg")),
    VOICE(2, "voice", Lists.newArrayList("mp3", "wav", "pcm")),
    VIDEO(3, "video", Lists.newArrayList("mp4")),
    DOC_FILE(4, "file", Lists.newArrayList("pdf", "ppt", "doc", "docx", "txt", "xls", "xlsx")),
    H5(5, "url", Lists.newArrayList()),
    CARD(6, "card", Lists.newArrayList()),
    NOTIFY(7, "notify", Lists.newArrayList());

    @EnumValue
    private final Integer dbValue;
    private final String labelText;
    private final List<String> suffix;

    public static ContentType labelOf(String labelText) {
        return Arrays.stream(ContentType.values())
                .filter(one -> one.labelText.equals(labelText))
                .findFirst()
                .orElse(null);


    }
}
