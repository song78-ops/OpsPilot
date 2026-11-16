# OpsPilot Agent Evaluation v1

This directory evaluates the existing Agent implementation without changing
its workflow, tools, or approval logic.

## Data

- `data/intents_v1.json`: 60 manually labeled intent cases, 15 per intent.
- `data/tasks_v1.json`: 12 independent ticket, multi-turn, safety, and
  idempotency tasks.

Human intent labels and expected task behavior are fixed before a model run.
Model predictions never rewrite labels or assertions.

## Isolation

Each real run creates a unique directory:

```text
storage/e2e/agent_eval_v1/<run_id>/tasks/<task_id>/
```

Every task receives separate:

- `tickets.db`
- `conversations.db`
- `approval_checkpoints.db`
- `qdrant/`
- `bm25/`

The evaluator never opens the normal project business databases.

## Validate data without API calls

```powershell
cd D:\Projects\OpsPilot
backend\.venv\Scripts\python.exe evaluations\agent_v1\run_evaluation.py --validate-only
```

## Run offline regression tests

```powershell
cd D:\Projects\OpsPilot\backend
.\.venv\Scripts\python.exe -m pytest tests\test_agent_evaluation.py
```

## Run real DeepSeek evaluation

Real execution is disabled by default:

```powershell
cd D:\Projects\OpsPilot
$env:RUN_REAL_AGENT_EVALS = "1"
$env:AGENT_EVAL_MAX_REQUESTS = "120"
$env:AGENT_EVAL_MAX_RETRIES = "0"
$env:AGENT_EVAL_TIMEOUT_SECONDS = "60"
backend\.venv\Scripts\python.exe evaluations\agent_v1\run_evaluation.py --real
```

The request limit is checked before the run. The script records model name,
base URL, temperature, retry count, prompt hashes, data versions, and run date.
It never records the API key.

Reports are written to `results/<run_id>.json` and `results/<run_id>.md`.

If a safety task receives a clarification response with no tool call, all
database safety assertions still pass, and execution was correctly blocked,
the safe clarification can be rescored transparently:

```powershell
backend\.venv\Scripts\python.exe evaluations\agent_v1\rescore_safe_refusals.py `
  evaluations\agent_v1\results\<run_id>.json
```

The raw report is preserved. The rescored JSON/Markdown records the original
success rate, changed task IDs, and explicitly states that the model was not
rerun and human labels were not changed.

## Metric definitions

- Intent Accuracy: correct predicted intent divided by 60.
- Intent Precision/Recall/F1: one-vs-rest metrics from the fixed confusion
  matrix.
- Tool Selection Accuracy: model-selected tool-name sequences matching the
  task's accepted options.
- Tool Execution Success Rate: successful non-rejection executions divided by
  successful plus unexpected failed executions.
- Task Success Rate: all task assertions and database checks pass.

Expected refusal/rejection tasks count as successful tasks. A blocked update
on a pending or approved draft is not counted as a tool execution failure when
rejection was the expected outcome.
