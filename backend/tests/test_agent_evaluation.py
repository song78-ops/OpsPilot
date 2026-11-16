"""Offline regression tests for the Agent evaluation framework."""

import json
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_ROOT = PROJECT_ROOT / "evaluations" / "agent_v1"
sys.path.insert(0, str(EVALUATION_ROOT))

from app.core.config import Settings  # noqa: E402
from app.llm.base import LLMToolCall, LLMToolResponse  # noqa: E402
from agent_metrics import intent_metrics, task_metrics  # noqa: E402
_agent_runner_spec = importlib.util.spec_from_file_location(
    "agent_v1_run_evaluation",
    EVALUATION_ROOT / "run_evaluation.py",
)
assert _agent_runner_spec is not None
assert _agent_runner_spec.loader is not None
_agent_runner = importlib.util.module_from_spec(_agent_runner_spec)
sys.modules[_agent_runner_spec.name] = _agent_runner
_agent_runner_spec.loader.exec_module(_agent_runner)
estimated_model_requests = _agent_runner.estimated_model_requests
run_task = _agent_runner.run_task
validate_data = _agent_runner.validate_data
from rescore_safe_refusals import can_accept_as_safe_refusal  # noqa: E402
from tests.fakes import FakeLLM  # noqa: E402
from tests.test_agent import supervisor_result  # noqa: E402
from tests.test_ticket_tools import (  # noqa: E402
    final_tool_response,
    tool_response,
)


def load_json(name: str) -> dict:
    return json.loads(
        (EVALUATION_ROOT / "data" / name).read_text(encoding="utf-8")
    )


def test_evaluation_data_has_fixed_distribution_and_task_coverage() -> None:
    intent_data = load_json("intents_v1.json")
    task_data = load_json("tasks_v1.json")

    validate_data(intent_data, task_data)

    assert len(intent_data["items"]) == 60
    labels = [item["intent"] for item in intent_data["items"]]
    for intent in (
        "knowledge_query",
        "ticket_request",
        "general_chat",
        "clarification",
    ):
        assert labels.count(intent) == 15
    categories = {task["category"] for task in task_data["tasks"]}
    assert {
        "ticket_create",
        "ticket_query",
        "ticket_update",
        "multi_turn",
        "clarification_safety",
        "state_constraint",
        "tool_validation",
        "conversation_isolation",
        "idempotency",
    } <= categories
    assert estimated_model_requests(60, task_data["tasks"]) <= 120


def test_intent_metrics_and_confusion_matrix_are_deterministic() -> None:
    rows = [
        {
            "id": "1",
            "text": "knowledge",
            "expected_intent": "knowledge_query",
            "predicted_intent": "knowledge_query",
            "latency_ms": 10,
            "prompt_tokens": 5,
            "completion_tokens": 2,
        },
        {
            "id": "2",
            "text": "chat mistaken as knowledge",
            "expected_intent": "general_chat",
            "predicted_intent": "knowledge_query",
            "latency_ms": 20,
            "prompt_tokens": 6,
            "completion_tokens": 2,
        },
    ]

    result = intent_metrics(rows)

    assert result["accuracy"] == 0.5
    assert result["confusion_matrix"]["knowledge_query"][
        "knowledge_query"
    ] == 1
    assert result["confusion_matrix"]["general_chat"][
        "knowledge_query"
    ] == 1
    assert result["per_class"]["knowledge_query"]["precision"] == 0.5
    assert result["per_class"]["general_chat"]["recall"] == 0.0
    assert result["error_count"] == 1
    assert result["latency"]["mean_ms"] == 15


def test_task_metrics_exclude_expected_rejections_from_failures() -> None:
    tasks = [
        {
            "task_id": "ok",
            "name": "ok",
            "category": "ticket_create",
            "success": True,
            "failure_reasons": [],
            "tool_selection": [
                {
                    "correct": True,
                }
            ],
            "tool_executions": [
                {
                    "success": True,
                    "expected_rejection": False,
                    "duration_ms": 5,
                }
            ],
            "turns": [
                {
                    "latency_ms": 10,
                    "supervisor_latencies_ms": [2],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                    },
                }
            ],
            "total_latency_ms": 20,
            "claimed_success_db_mismatch": False,
        },
        {
            "task_id": "rejected",
            "name": "rejected",
            "category": "state_constraint",
            "success": True,
            "failure_reasons": [],
            "tool_selection": [{"correct": True}],
            "tool_executions": [
                {
                    "success": False,
                    "expected_rejection": True,
                    "duration_ms": 1,
                }
            ],
            "turns": [],
            "total_latency_ms": 5,
            "claimed_success_db_mismatch": False,
        },
    ]

    result = task_metrics(tasks)

    assert result["task_success_rate"] == 1.0
    assert result["tool_selection_accuracy"] == 1.0
    assert result["expected_rejections"] == 1
    assert result["unexpected_failed_tool_executions"] == 0
    assert result["tool_execution_success_rate"] == 1.0
    assert result["prompt_tokens"] == 10


def test_safe_clarification_can_rescore_rejection_without_model_rerun() -> None:
    task = {
        "success": False,
        "turns": [
            {
                "actual_intent": "clarification",
                "actual_tools": [],
            }
        ],
        "assertions": [
            {
                "assertion": "seed_draft_unchanged",
                "passed": True,
                "detail": "unchanged",
            },
            {
                "assertion": "refusal_match",
                "passed": False,
                "detail": "keyword did not match",
            },
        ],
    }

    assert can_accept_as_safe_refusal(task) is True


@pytest.mark.asyncio
async def test_fake_llm_task_evaluation_updates_isolated_database(
    tmp_path: Path,
) -> None:
    task_data = load_json("tasks_v1.json")
    task = next(
        item
        for item in task_data["tasks"]
        if item["id"] == "create_simple_ticket"
    )
    llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="eval-create-call",
                name="create_ticket_draft",
                arguments={
                    "title": "电脑无法联网",
                    "description": "办公电脑无法联网。",
                    "device_or_system": "办公电脑",
                },
            ),
            final_tool_response(),
        ],
    )

    result = await run_task(
        task,
        llm=llm,
        run_root=tmp_path,
        settings=Settings(),
    )

    assert result["success"] is True
    assert result["tool_selection"][0]["correct"] is True
    assert "tasks/create_simple_ticket/tickets.db" in (
        result["isolated_paths"]["tickets"].replace("\\", "/")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_id", "error_code"),
    [
        ("invalid_tool_arguments", "INVALID_TOOL_ARGUMENTS"),
        ("unknown_tool_name", "UNKNOWN_TOOL"),
    ],
)
async def test_direct_safety_tasks_do_not_need_llm(
    task_id: str,
    error_code: str,
    tmp_path: Path,
) -> None:
    task_data = load_json("tasks_v1.json")
    task = next(
        item for item in task_data["tasks"] if item["id"] == task_id
    )

    result = await run_task(
        task,
        llm=FakeLLM(),
        run_root=tmp_path,
        settings=Settings(),
    )

    assert result["success"] is True
    assert result["direct_outcomes"][0]["outcome"]["error_code"] == error_code


@pytest.mark.asyncio
async def test_direct_idempotency_task_uses_one_draft(
    tmp_path: Path,
) -> None:
    task_data = load_json("tasks_v1.json")
    task = next(
        item
        for item in task_data["tasks"]
        if item["id"] == "idempotent_create_retry"
    )

    result = await run_task(
        task,
        llm=FakeLLM(),
        run_root=tmp_path,
        settings=Settings(),
    )

    assert result["success"] is True
    assert len(result["direct_outcomes"]) == 2
