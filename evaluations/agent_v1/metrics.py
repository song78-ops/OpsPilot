"""Pure metric and report helpers for the Agent evaluations."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any

INTENTS = (
    "knowledge_query",
    "ticket_request",
    "general_chat",
    "clarification",
)


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, math.ceil((len(ordered) - 1) * ratio)),
    )
    return ordered[index]


def latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "mean_ms": statistics.mean(values) if values else 0.0,
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
    }


def intent_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = list(INTENTS)
    confusion = {
        expected: {predicted: 0 for predicted in labels}
        for expected in labels
    }
    correct = 0
    for row in rows:
        expected = row["expected_intent"]
        predicted = row["predicted_intent"]
        if predicted in labels:
            confusion[expected][predicted] += 1
        if predicted == expected:
            correct += 1

    per_class: dict[str, dict[str, float | int]] = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in labels if other != label)
        fn = sum(
            confusion[label][other]
            for other in labels
            if other != label
        )
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        f1 = safe_div(2 * precision * recall, precision + recall)
        per_class[label] = {
            "support": sum(confusion[label].values()),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    errors = [
        row for row in rows
        if row["predicted_intent"] != row["expected_intent"]
    ]
    return {
        "total": len(rows),
        "accuracy": safe_div(correct, len(rows)),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "error_count": len(errors),
        "errors": errors,
        "latency": latency_summary(
            [float(row["latency_ms"]) for row in rows]
        ),
        "prompt_tokens": sum(int(row.get("prompt_tokens", 0)) for row in rows),
        "completion_tokens": sum(
            int(row.get("completion_tokens", 0)) for row in rows
        ),
    }


def task_metrics(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    selection_rows = [
        selection
        for task in tasks
        for selection in task.get("tool_selection", [])
    ]
    selection_correct = sum(
        1 for row in selection_rows if row["correct"]
    )

    successful_tools = 0
    unexpected_failed_tools = 0
    expected_rejections = 0
    tool_latencies: list[float] = []
    supervisor_latencies: list[float] = []
    agent_latencies: list[float] = []
    task_latencies: list[float] = []
    prompt_tokens = 0
    completion_tokens = 0

    for task in tasks:
        task_latencies.append(float(task.get("total_latency_ms", 0.0)))
        for execution in task.get("tool_executions", []):
            tool_latencies.append(float(execution.get("duration_ms", 0.0)))
            if execution.get("success"):
                successful_tools += 1
            elif execution.get("expected_rejection"):
                expected_rejections += 1
            else:
                unexpected_failed_tools += 1
        for turn in task.get("turns", []):
            agent_latencies.append(float(turn.get("latency_ms", 0.0)))
            supervisor_latencies.extend(
                float(value)
                for value in turn.get("supervisor_latencies_ms", [])
            )
            usage = turn.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens", 0))
            completion_tokens += int(usage.get("completion_tokens", 0))

    failures = [
        {
            "task_id": task["task_id"],
            "name": task["name"],
            "category": task["category"],
            "failure_reasons": task.get("failure_reasons", []),
        }
        for task in tasks
        if not task.get("success")
    ]
    return {
        "total_tasks": len(tasks),
        "successful_tasks": sum(1 for task in tasks if task["success"]),
        "task_success_rate": safe_div(
            sum(1 for task in tasks if task["success"]),
            len(tasks),
        ),
        "tool_selection_total": len(selection_rows),
        "tool_selection_correct": selection_correct,
        "tool_selection_accuracy": safe_div(
            selection_correct,
            len(selection_rows),
        ),
        "successful_tool_executions": successful_tools,
        "unexpected_failed_tool_executions": unexpected_failed_tools,
        "expected_rejections": expected_rejections,
        "tool_execution_success_rate": safe_div(
            successful_tools,
            successful_tools + unexpected_failed_tools,
        ),
        "task_latency": latency_summary(task_latencies),
        "agent_turn_latency": latency_summary(agent_latencies),
        "supervisor_latency": latency_summary(supervisor_latencies),
        "tool_latency": latency_summary(tool_latencies),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "failures": failures,
        "claimed_success_db_mismatches": [
            task for task in tasks
            if task.get("claimed_success_db_mismatch")
        ],
    }


def task_category_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(task["category"] for task in tasks))


def markdown_report(result: dict[str, Any]) -> str:
    meta = result["metadata"]
    intent = result["intent_evaluation"]
    tasks = result["task_evaluation"]
    lines = [
        "# OpsPilot Agent v1 Evaluation",
        "",
        f"- Run: `{meta['run_id']}`",
        f"- Date: {meta['run_date']}",
        f"- Configured model: `{meta['model']}`",
        f"- Observed provider models: "
        f"`{', '.join(meta.get('observed_models', [])) or 'unknown'}`",
        f"- Intent data: `{meta['intent_data_version']}`",
        f"- Task data: `{meta['task_data_version']}`",
        f"- Temperature: `{meta['temperature']}`",
        f"- Max retries: `{meta['max_retries']}`",
        "",
        "## Intent classification",
        "",
        f"- Cases: {intent['total']}",
        f"- Accuracy: {intent['accuracy']:.4f}",
        f"- Errors: {intent['error_count']}",
        f"- Mean latency: {intent['latency']['mean_ms']:.2f} ms",
        f"- P50 / P95: {intent['latency']['p50_ms']:.2f} / "
        f"{intent['latency']['p95_ms']:.2f} ms",
        f"- Prompt / completion tokens: {intent['prompt_tokens']} / "
        f"{intent['completion_tokens']}",
        "",
        "| Intent | Precision | Recall | F1 | Support |",
        "|---|---:|---:|---:|---:|",
    ]
    for label in INTENTS:
        row = intent["per_class"][label]
        lines.append(
            f"| {label} | {row['precision']:.4f} | "
            f"{row['recall']:.4f} | {row['f1']:.4f} | "
            f"{row['support']} |"
        )

    lines.extend([
        "",
        "### Confusion matrix",
        "",
        "Rows are the fixed human labels; columns are model predictions.",
        "",
        "| Expected \\ Predicted | knowledge | ticket | chat | clarification |",
        "|---|---:|---:|---:|---:|",
    ])
    short_names = {
        "knowledge_query": "knowledge_query",
        "ticket_request": "ticket_request",
        "general_chat": "general_chat",
        "clarification": "clarification",
    }
    for expected in INTENTS:
        matrix = intent["confusion_matrix"][expected]
        lines.append(
            f"| {short_names[expected]} | "
            + " | ".join(str(matrix[label]) for label in INTENTS)
            + " |"
        )

    lines.extend([
        "",
        "### Typical intent errors",
        "",
    ])
    if intent["errors"]:
        for row in intent["errors"][:20]:
            lines.append(
                f"- `{row['id']}` {row['text']} → "
                f"`{row['predicted_intent']}` (expected "
                f"`{row['expected_intent']}`)"
            )
    else:
        lines.append("No incorrect predictions.")

    lines.extend([
        "",
        "## Tool and multi-turn tasks",
        "",
        f"- Tasks: {tasks['total_tasks']}",
        f"- Task success rate: {tasks['task_success_rate']:.4f}",
        f"- Tool selection accuracy: "
        f"{tasks['tool_selection_accuracy']:.4f}",
        f"- Tool execution success rate: "
        f"{tasks['tool_execution_success_rate']:.4f}",
        f"- Expected rejected operations: {tasks['expected_rejections']}",
        f"- Unexpected failed tool executions: "
        f"{tasks['unexpected_failed_tool_executions']}",
        "",
        "### Latency",
        "",
        "| Scope | Mean | P50 | P95 |",
        "|---|---:|---:|---:|",
    ])
    for key, label in (
        ("task_latency", "Task total"),
        ("agent_turn_latency", "Agent turn"),
        ("supervisor_latency", "Supervisor"),
        ("tool_latency", "Tool"),
    ):
        row = tasks[key]
        lines.append(
            f"| {label} | {row['mean_ms']:.2f} ms | "
            f"{row['p50_ms']:.2f} ms | {row['p95_ms']:.2f} ms |"
        )

    lines.extend([
        "",
        f"- Task prompt tokens: {tasks['prompt_tokens']}",
        f"- Task completion tokens: {tasks['completion_tokens']}",
        "",
        "### Failed tasks",
        "",
    ])
    if tasks["failures"]:
        for failure in tasks["failures"]:
            lines.append(
                f"- `{failure['task_id']}` ({failure['category']}): "
                + "; ".join(failure["failure_reasons"])
            )
    else:
        lines.append("No failed tasks.")

    lines.extend([
        "",
        "## Database consistency",
        "",
        f"- Claimed success but DB mismatch cases: "
        f"{len(tasks['claimed_success_db_mismatches'])}",
        "",
    ])
    rescoring = meta.get("rescoring")
    if rescoring:
        lines.extend([
            "## Safe-refusal rescoring",
            "",
            f"- Raw task success rate: "
            f"{rescoring['raw_task_success_rate']:.4f}",
            f"- Rescored task success rate: "
            f"{tasks['task_success_rate']:.4f}",
            f"- Changed tasks: {', '.join(rescoring['changed_task_ids']) or 'none'}",
            f"- Policy: {rescoring['policy']}",
            f"- Model rerun: {rescoring['model_rerun']}",
            f"- Human labels changed: {rescoring['labels_changed']}",
            "",
        ])
    lines.extend([
        "## Notes",
        "",
        "- Human intent labels are fixed in `data/intents_v1.json`.",
        "- Expected rejected operations count as task success and are excluded "
        "from tool execution failures.",
        "- Every task uses an isolated SQLite, conversation and approval "
        "checkpoint directory.",
        "- The run script never writes API keys to logs or result files.",
        "",
    ])
    return "\n".join(lines)
