# OpsPilot RAG QA v1 Evaluation

This evaluation measures answer quality, citation reliability, refusal
behavior, and reranker quality without changing production RAG logic.

## Dataset

- `data/questions_v1.json`: 50 questions, 30 answerable and 20 unanswerable.
- 8 questions are explicitly labeled as prompt injection, conflict,
  misleading, destructive, or authority-spoofing scenarios.
- Every answerable question contains manually verified expected facts and gold
  document/Chunk keys.
- Existing ten retrieval documents are reused from
  `evaluations/rag_retrieval_v1`.
- Three evaluation-only documents cover a true multi-Chunk scenario and
  explicitly marked untrusted or legacy conflicting information.

Symbolic gold document and Chunk keys are resolved to runtime IDs after
ingestion. Gold labels are never changed from model output.

## Isolation

Each run creates:

```text
storage/e2e/rag_qa_v1/<run_id>/
├── documents/
├── qdrant/
└── bm25/
```

The normal user knowledge base, BM25 index, Qdrant directory, and business
databases are not opened.

## Validate without paid calls

```powershell
cd D:\Projects\OpsPilot
backend\.venv\Scripts\python.exe evaluations\rag_qa_v1\run_evaluation.py --validate-only
```

## Offline tests

```powershell
cd D:\Projects\OpsPilot\backend
.\.venv\Scripts\python.exe -m pytest tests\test_rag_qa_evaluation.py
```

## Real DeepSeek run

Real execution is disabled by default:

```powershell
cd D:\Projects\OpsPilot
$env:RUN_REAL_RAG_QA_EVALS = "1"
$env:RAG_QA_MAX_REQUESTS = "100"
$env:RAG_QA_MAX_RETRIES = "0"
$env:RAG_QA_TIMEOUT_SECONDS = "60"
backend\.venv\Scripts\python.exe evaluations\rag_qa_v1\run_evaluation.py --real
```

Both modes use the same document snapshot, questions, Top-K, Candidate-K,
embedding model, generation prompt, model configuration, and temperature.

## Metrics

- Recall@3, MRR@5, and binary nDCG@5 use gold Chunk keys.
- Answer Correctness is mean manually authored fact coverage across answerable
  questions, with refusals contributing zero.
- Answer Completeness is fact coverage among actually answered questions.
- Groundedness requires an expected fact found in the answer to also appear in
  at least one cited source.
- Citation Validity checks structural citation-to-source mapping.
- Citation Support Accuracy requires factual claims to be supported by cited
  evidence; it is stricter than citation-number validity.
- Correct refusal is measured separately for unanswerable and safety
  questions.

No LLM-as-a-Judge output is used as ground truth. Ambiguous or partial matches
remain `pending_review`.

## Safe-refusal rescoring

An unanswerable safety question can be answered with a grounded explicit denial
such as “不可以” instead of `insufficient_evidence`.

```powershell
backend\.venv\Scripts\python.exe evaluations\rag_qa_v1\rescore_safe_refusals.py `
  evaluations\rag_qa_v1\results\<run_id>.json
```

The raw report is preserved. Rescored JSON/Markdown records the original
unsupported-answer rate, changed question IDs, and states that the model was
not rerun and human labels were not changed.
