from app.util.display_text import brief_school_major_text, clean_plan_sample_text


def test_brief_school_major_text_removes_long_admission_notes():
    text = brief_school_major_text(
        "河北师范大学第201组(中外合作办学组)",
        "翻译(中外合作办学)(合作方：英国斯特灵大学；要求外语单科成绩不低于95分，前三年就读于河北师范大学)",
    )

    assert text == "河北师范大学第201组-翻译"
    assert "合作方" not in text
    assert "前三年" not in text


def test_clean_plan_sample_text_preserves_position_and_tier_suffix():
    text = clean_plan_sample_text(
        "青岛理工大学-建筑学(中外合作办学)(与韩国光云大学合作)(冲)@1"
    )

    assert text == "青岛理工大学-建筑学(冲)第1位"
    assert "合作" not in text
