from app.domain.intent_polarity import negative_constraint_reversal_clauses, parse_constraint_polarity_operation


def test_parse_negative_constraint_reversal_returns_structured_operation():
    operation = parse_constraint_polarity_operation("不要排除经济学类啊")

    assert operation is not None
    assert operation.operation == "remove_negative_constraint"
    assert operation.target_polarity == "negative"
    assert operation.replacement_polarity == "positive"
    assert operation.replacement_strength == "acceptable"


def test_parse_negative_constraint_reversal_ignores_plain_negative_statement():
    assert parse_constraint_polarity_operation("经济学类不要") is None


def test_negative_constraint_reversal_clauses_only_return_operation_segments():
    clauses = negative_constraint_reversal_clauses("不要排除经济学类，但临床医学还是排除，别避开东北")

    assert clauses == ["不要排除经济学类", "别避开东北"]
