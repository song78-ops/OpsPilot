# RAG Retrieval Evaluation Results

| Mode | Recall@3 | MRR@5 | nDCG@5 | Mean ms | P50 ms | P95 ms | No-answer returns |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 1.0000 | 0.9333 | 0.9505 | 10.90 | 10.71 | 12.30 | 5/5 |
| bm25 | 1.0000 | 1.0000 | 1.0000 | 0.43 | 0.42 | 0.56 | 4/5 |
| hybrid | 1.0000 | 0.9800 | 0.9852 | 11.17 | 11.09 | 12.55 | 5/5 |
| hybrid_reranker | 1.0000 | 0.9800 | 0.9852 | 866.58 | 861.01 | 914.51 | 5/5 |

## Reranker Performance

- Load: 2569.05 ms
- Warm single inference: 38.59 ms
- Batch 10 inference: 171.05 ms

| Candidate K | Mean ms | P50 ms | P95 ms |
|---:|---:|---:|---:|
| 5 | 478.10 | 471.95 | 516.31 |
| 10 | 869.61 | 870.69 | 926.19 |
| 20 | 853.36 | 841.09 | 915.87 |
