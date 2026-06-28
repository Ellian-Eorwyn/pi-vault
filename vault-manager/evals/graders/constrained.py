"""Grade constrained-vocabulary fields (type, status, domain, source_kind,
capture_type, folder, hub).

These are exact-match classification tasks, so grading is token-free: accuracy,
per-class precision/recall/F1, macro-F1, and a confusion matrix. The grader
normalises predictions defensively (the engine's validators already coerce most
shapes, but raw model output may arrive as a one-item list or with stray case).
"""

from __future__ import annotations

from typing import Any


def normalise(value: Any) -> str:
    """Collapse a field value to a comparable token.

    The vault's frontmatter has historically stored ``domain`` as both a scalar
    and a one-item list (``domains:``), so a list is reduced to its first member.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip().lower()


def grade_field(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Grade one field across notes.

    ``items`` is a list of ``{"pred": ..., "gold": ...}``. Returns accuracy, a
    per-class P/R/F1 table, macro-F1 over classes that appear in the gold, and a
    nested confusion matrix ``confusion[gold][pred] = count``.
    """
    n = len(items)
    correct = 0
    labels: set[str] = set()
    tp: dict[str, int] = {}
    fp: dict[str, int] = {}
    fn: dict[str, int] = {}
    confusion: dict[str, dict[str, int]] = {}

    for item in items:
        pred = normalise(item.get("pred"))
        gold = normalise(item.get("gold"))
        labels.update({pred, gold})
        confusion.setdefault(gold, {})
        confusion[gold][pred] = confusion[gold].get(pred, 0) + 1
        if pred == gold:
            correct += 1
            tp[gold] = tp.get(gold, 0) + 1
        else:
            fp[pred] = fp.get(pred, 0) + 1
            fn[gold] = fn.get(gold, 0) + 1

    gold_labels = sorted({normalise(item.get("gold")) for item in items})
    per_class: dict[str, dict[str, float]] = {}
    f1s: list[float] = []
    for label in sorted(labels):
        t = tp.get(label, 0)
        precision = t / (t + fp.get(label, 0)) if (t + fp.get(label, 0)) else 0.0
        recall = t / (t + fn.get(label, 0)) if (t + fn.get(label, 0)) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        support = sum(confusion.get(label, {}).values())
        per_class[label or "(empty)"] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }
        if label in gold_labels:
            f1s.append(f1)

    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "correct": correct,
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "per_class": per_class,
        "confusion": confusion,
    }


def grade_fields(records: list[dict[str, Any]], fields: list[str]) -> dict[str, Any]:
    """Grade several fields at once.

    ``records`` is per-note with ``pred`` and ``gold`` sub-dicts; only notes that
    carry a gold value for a field contribute to that field's score.
    """
    out: dict[str, Any] = {}
    for field in fields:
        items = [
            {"pred": rec.get("pred", {}).get(field), "gold": rec["gold"][field]}
            for rec in records
            if field in rec.get("gold", {})
        ]
        if items:
            out[field] = grade_field(items)
    return out
