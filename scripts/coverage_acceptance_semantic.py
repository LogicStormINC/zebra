"""Score independently labeled coverage outputs; no inferred ground truth."""

import argparse
import json
from collections import Counter
from pathlib import Path

OUTCOMES = {"finding", "clear", "unresolved"}


def indexed(path: Path) -> dict[str, dict]:
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError("each record must be an object")
        key = item.get("case_id")
        if not isinstance(key, str) or not key.strip() or key in records:
            raise ValueError("case_id must be nonempty and unique")
        records[key] = item
    if not records:
        raise ValueError("acceptance requires a nonempty labeled dataset")
    return records


def evaluate(labels: dict, predictions: dict, *, independent: bool) -> dict:
    if not labels:
        raise ValueError("acceptance requires a nonempty labeled dataset")
    if labels.keys() != predictions.keys():
        raise ValueError("predictions must cover exactly the labeled dataset")
    matrix: Counter = Counter()
    quotes = correct_quotes = 0
    for key, gold in labels.items():
        prediction = predictions[key]
        if not isinstance(gold, dict) or not isinstance(prediction, dict):
            raise ValueError("labels and predictions must be objects")
        expected, source = gold.get("expected"), gold.get("text")
        actual = prediction.get("outcome")
        if (
            not isinstance(expected, str)
            or not isinstance(actual, str)
            or expected not in OUTCOMES
            or actual not in OUTCOMES
            or not isinstance(source, str)
        ):
            raise ValueError("text and explicit finding/clear/unresolved labels are required")
        matrix[expected, actual] += 1
        evidence = prediction.get("quotes")
        if not isinstance(evidence, list):
            raise ValueError("quotes must be an explicit list")
        if (actual == "finding" and not evidence) or (actual == "clear" and evidence):
            raise ValueError("finding requires quotes; clear must not contain quotes")
        for quote in evidence:
            if not isinstance(quote, dict):
                raise ValueError("each quote must be an object")
            quotes += 1
            start, end, text = quote.get("start"), quote.get("end"), quote.get("text")
            correct_quotes += int(
                type(start) is int
                and type(end) is int
                and isinstance(text, str)
                and 0 <= start < end <= len(source)
                and source[start:end] == text
            )
    true_positive = matrix["finding", "finding"]
    false_positive = sum(matrix[label, "finding"] for label in OUTCOMES - {"finding"})
    false_negative = sum(matrix["finding", label] for label in OUTCOMES - {"finding"})

    def divide(numerator, denominator):
        return numerator / denominator if denominator else None

    return {
        "schema": "zebra.coverage-semantic-acceptance.v1",
        "evidence": "independent_labels" if independent else "controls_only",
        "business_accuracy_claim": False,
        "eligible_for_business_acceptance": independent,
        "cases": len(labels),
        "precision": divide(true_positive, true_positive + false_positive),
        "recall": divide(true_positive, true_positive + false_negative),
        "unknown_rate": sum(
            count for (_, actual), count in matrix.items() if actual == "unresolved"
        )
        / len(labels),
        "quote_correctness": divide(correct_quotes, quotes),
        "missed_findings": false_negative,
        "confusion": {
            f"{expected}->{actual}": count for (expected, actual), count in sorted(matrix.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--label-source", choices=["independent", "controls"], required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--min-precision", type=float, required=True)
    parser.add_argument("--min-recall", type=float, required=True)
    parser.add_argument("--max-unknown", type=float, required=True)
    args = parser.parse_args()
    thresholds = (args.min_precision, args.min_recall, args.max_unknown)
    if any(not 0 <= value <= 1 for value in thresholds):
        parser.error("thresholds must be finite and within [0,1]")
    report = evaluate(
        indexed(args.labels),
        indexed(args.predictions),
        independent=args.label_source == "independent",
    )
    report.update(profile=args.profile, thresholds=thresholds)
    report["passed"] = (
        report["precision"] is not None
        and report["recall"] is not None
        and report["precision"] >= args.min_precision
        and report["recall"] >= args.min_recall
        and report["unknown_rate"] <= args.max_unknown
        and report["quote_correctness"] == 1
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
