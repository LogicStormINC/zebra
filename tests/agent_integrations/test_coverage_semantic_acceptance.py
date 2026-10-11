"""Acceptance metrics never substitute unresolved outputs or invented labels."""

import pytest

from scripts.coverage_acceptance_semantic import evaluate


def samples():
    labels = {
        "positive": {"expected": "finding", "text": "🙂停产"},
        "negative": {"expected": "clear", "text": "天气晴朗"},
        "missed": {"expected": "finding", "text": "发生事故"},
    }
    predictions = {
        "positive": {"outcome": "finding", "quotes": [{"start": 1, "end": 3, "text": "停产"}]},
        "negative": {"outcome": "clear", "quotes": []},
        "missed": {"outcome": "unresolved", "quotes": []},
    }
    return labels, predictions


def test_unknown_is_a_missed_finding_not_a_negative():
    result = evaluate(*samples(), independent=False)
    assert result["precision"] == 1 and result["recall"] == 0.5
    assert result["unknown_rate"] == 1 / 3 and result["missed_findings"] == 1
    assert result["quote_correctness"] == 1 and not result["business_accuracy_claim"]


def test_incorrect_unicode_quote_is_reported():
    labels, predictions = samples()
    predictions["positive"]["quotes"][0]["start"] = 0
    assert evaluate(labels, predictions, independent=True)["quote_correctness"] == 0


@pytest.mark.parametrize("damage", ["missing", "extra", "label", "empty_quote", "empty"])
def test_invalid_or_incomplete_corpus_refuses(damage):
    labels, predictions = samples()
    if damage == "missing":
        predictions.pop("negative")
    elif damage == "extra":
        predictions["foreign"] = predictions["negative"]
    elif damage == "label":
        labels["positive"]["expected"] = "unknown"
    elif damage == "empty_quote":
        predictions["positive"]["quotes"] = []
    else:
        labels.clear()
        predictions.clear()
    with pytest.raises(ValueError):
        evaluate(labels, predictions, independent=False)
