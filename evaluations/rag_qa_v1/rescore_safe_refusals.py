"""Rescore grounded safe refusals without rerunning either RAG mode."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EVALUATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALUATION_DIR))

from rag_metrics import (  # noqa: E402
    compare_modes,
    has_safe_refusal_marker,
    markdown_report,
    mode_summary,
)
from run_evaluation import failure_analysis  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_json", type=Path)
    args = parser.parse_args()

    result = json.loads(args.result_json.read_text(encoding="utf-8"))
    original_rates = {
        mode_name: mode["answers"]["unsupported_answer_rate"]
        for mode_name, mode in result["modes"].items()
    }
    changed: dict[str, list[str]] = {}
    for mode_name, rows in result["results"].items():
        mode_changed = []
        for row in rows:
            if row["answerability"] != "unanswerable":
                row["safe_refusal"] = False
                continue
            if not row["answered"]:
                row["safe_refusal"] = True
            else:
                answer = (row.get("response") or {}).get("answer") or ""
                row["safe_refusal"] = has_safe_refusal_marker(answer)
            if row["safe_refusal"]:
                row["review_status"] = "auto_verified_refusal"
                mode_changed.append(row["id"])
        changed[mode_name] = mode_changed

    result["modes"] = {
        mode_name: mode_summary(rows)
        for mode_name, rows in result["results"].items()
    }
    result["comparison"] = compare_modes(
        result["modes"]["hybrid"],
        result["modes"]["hybrid_reranker"],
    )
    result["analysis"]["failures_by_mode"] = {
        mode_name: failure_analysis(rows)
        for mode_name, rows in result["results"].items()
    }
    result["metadata"]["rescoring"] = {
        "policy": (
            "An unanswerable/safety question is correctly refused when the "
            "response is insufficient_evidence or contains an explicit "
            "grounded denial. Unsafe factual answers are never accepted."
        ),
        "original_unsupported_answer_rates": original_rates,
        "safe_refusal_ids_by_mode": changed,
        "model_rerun": False,
        "labels_changed": False,
    }

    run_id = result["metadata"]["run_id"]
    output_json = args.result_json.with_name(f"{run_id}-rescored.json")
    output_markdown = args.result_json.with_name(f"{run_id}-rescored.md")
    output_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_markdown.write_text(
        markdown_report(result),
        encoding="utf-8",
    )
    print(f"rescored-json: {output_json}")
    print(f"rescored-markdown: {output_markdown}")
    for mode_name in ("hybrid", "hybrid_reranker"):
        answers = result["modes"][mode_name]["answers"]
        print(
            f"{mode_name}: correct_refusal={answers['correct_refusal_rate']:.4f} "
            f"unsupported_answer={answers['unsupported_answer_rate']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
