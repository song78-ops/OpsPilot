# RAG Retrieval Evaluation v1

本评测集包含 10 份非敏感知识文档和 30 个问题。相关文档标签在运行任何检索之前
人工制定，标签只使用文档文件名标识，不根据 Dense、BM25 或 Hybrid 的返回结果调整。

问题分布：

- 12 个明确关键词、错误代码或产品版本问题。
- 8 个同义词与语义改写问题。
- 5 个跨段落或跨文档问题。
- 5 个知识库无答案问题。

指标口径：

- Recall@3：前 3 个去重文档中命中的相关文档数除以全部人工相关文档数。
- MRR@5：前 5 个去重文档中第一个相关文档排名倒数的平均值。
- nDCG@5：按前 5 个去重文档和人工二元相关性计算归一化折损累计增益。
- 无答案问题不进入 Recall/MRR 分母，单独统计返回了任意结果的次数。
- 对比 Dense、BM25、Hybrid、Hybrid + Reranker 四种方案。
- 延迟包含查询向量生成、检索、融合与精排，不包含首次模型加载。

运行：

```powershell
cd D:\Projects\OpsPilot\backend
.\.venv\Scripts\Activate.ps1
python ..\evaluations\rag_retrieval_v1\run_evaluation.py
```

结果写入同目录的 `latest_results.json` 和 `latest_results.md`。

