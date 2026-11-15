# OpsPilot

OpsPilot 是一个面向企业内部知识库与智能工单场景的 AI Agent 平台。

当前已提供 FastAPI + DeepSeek 的非流式问答、SSE 流式问答、Vue3 聊天前端和
Agent 智能助手页面，
知识库文档上传、解析、清洗、文本切块、BGE Dense Embedding + Qdrant 检索，
BM25 + RRF 混合检索、BGE CrossEncoder CPU 精排，以及带引用校验的知识库增强问答。
LangGraph 已提供 Supervisor 意图识别、原生工具调用，以及基于
`interrupt()` / `Command(resume)` 的本地人工审批工作流；尚未包含正式工单提交、
正式身份认证、多租户、RAG SSE、多 Agent 循环和持久化 Agent 记忆。工单草稿和
审批状态保存在 SQLite。

## 环境要求

- Windows
- Python 3.11
- Node.js 22.12 或更高版本
- 可访问 DeepSeek API 的网络环境
- DeepSeek API Key

## 安装

在 PowerShell 中执行：

```powershell
cd D:\Projects\OpsPilot\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

首次使用时，创建本地环境变量文件：

```powershell
Copy-Item .env.example .env
```

然后编辑 `backend/.env`，填写真实 API Key：

```dotenv
DEEPSEEK_API_KEY=your_deepseek_api_key
```

`.env` 已加入 `.gitignore`，不要提交真实密钥。

## 启动服务

确保当前目录是 `backend`，虚拟环境已激活：

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

服务启动后可访问：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

## 知识库文档

支持上传以下格式：

- PDF
- DOCX
- TXT
- Markdown（`.md`、`.markdown`）

默认配置：

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `DOCUMENT_STORAGE_DIR` | `storage/documents` | 原始文件和元数据目录 |
| `DOCUMENT_MAX_UPLOAD_BYTES` | `10485760` | 单文件最大 10 MiB |
| `RAG_CHUNK_SIZE` | `800` | 清洗后的 Unicode 字符数 |
| `RAG_CHUNK_OVERLAP` | `120` | 相邻 Chunk 的重叠字符数 |

切块优先保留完整段落，长段落会进一步按句子拆分。PDF 文本按页提取并保留页码；
TXT、Markdown 和 DOCX 在当前解析器中不提供可靠页码，因此 `page_number` 为 `null`。

通过 Swagger 操作：

1. 打开 <http://127.0.0.1:8000/docs>。
2. 使用 `POST /api/v1/documents/upload` 上传文件。
3. 上传响应包含 `document_id` 和完整 `chunks`。
4. 使用 `GET /api/v1/documents` 查看文档列表。
5. 使用 `GET /api/v1/documents/{document_id}` 查看文档和全部 Chunk 正文。

PowerShell 上传示例：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/upload" `
  -F "file=@D:\path\to\manual.txt"
```

文档原始内容和元数据保存在本地，重启服务后仍可读取。`storage/documents` 已加入
`.gitignore`，不会把上传的企业文档提交到 Git。

常见错误：

- `415 UNSUPPORTED_DOCUMENT_TYPE`：扩展名不支持。
- `413 DOCUMENT_TOO_LARGE`：文件超过大小限制。
- `400 DOCUMENT_VALIDATION_ERROR`：空文件或文件名非法。
- `422 DOCUMENT_PARSE_ERROR`：损坏文档、无文字扫描 PDF 或无法提取文字。
- `404 DOCUMENT_NOT_FOUND`：文档 ID 不存在。

## Dense、BM25 与 Hybrid 检索

默认 Embedding 模型：

```text
BAAI/bge-small-zh-v1.5
```

模型在 CPU 上通过 SentenceTransformers 运行，不依赖 CUDA。模型只在进程内第一次
使用索引或检索接口时加载，之后的请求复用同一个实例。

### 下载模型

首次运行时会尝试通过 Hugging Face 下载并缓存到：

```text
storage/models/BAAI--bge-small-zh-v1.5
```

如果 Hugging Face 网络不可用，可以运行项目提供的 ModelScope 下载脚本：

```powershell
cd D:\Projects\OpsPilot\backend
.\.venv\Scripts\Activate.ps1
python scripts\download_bge_model.py
```

脚本会下载 safetensors 权重、tokenizer 和配置到同一个本地目录。后续启动直接读取
本地快照，不会重复下载。

Reranker 模型 `BAAI/bge-reranker-base` 默认缓存到：

```text
storage/models/BAAI--bge-reranker-base
```

下载命令：

```powershell
cd D:\Projects\OpsPilot\backend
.\.venv\Scripts\Activate.ps1
python scripts\download_reranker_model.py
```

### Qdrant Local

向量默认保存在：

```text
storage/qdrant
```

模型、维度、索引版本和查询指令会记录在：

```text
storage/qdrant-index-manifest.json
```

Qdrant Local 会锁定数据目录，同一路径只能由一个后端进程打开。本地开发请使用单个
Uvicorn worker，不要同时启动多个后端实例。如果目录已被占用，接口会返回
`503 VECTOR_STORE_UNAVAILABLE`。

默认配置：

| 配置项 | 默认值 |
|---|---:|
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-small-zh-v1.5` |
| `EMBEDDING_BATCH_SIZE` | `16` |
| `EMBEDDING_MAX_TOKENS` | `512` |
| `EMBEDDING_OVERLAP_TOKENS` | `64` |
| `EMBEDDING_QUERY_INSTRUCTION` | `为这个句子生成表示以用于检索相关文章：` |
| `QDRANT_STORAGE_DIR` | `storage/qdrant` |
| `BM25_STORAGE_DIR` | `storage/bm25` |
| `BM25_K1` | `1.5` |
| `BM25_B` | `0.75` |
| `RAG_INDEX_VERSION` | `1` |
| `RAG_RETRIEVAL_MAX_TOP_K` | `20` |
| `RAG_RRF_K` | `60` |
| `RAG_RRF_CANDIDATE_K` | `20` |
| `RERANKER_ENABLED` | `true` |
| `RERANKER_MODEL_NAME` | `BAAI/bge-reranker-base` |
| `RERANKER_BATCH_SIZE` | `8` |
| `RERANKER_MAX_LENGTH` | `512` |
| `RERANKER_OVERLAP_TOKENS` | `32` |
| `RERANKER_CANDIDATE_K` | `20` |
| `RAG_CONTEXT_MAX_TOKENS` | `3000` |
| `RAG_SOURCE_SUMMARY_CHARS` | `320` |
| `AGENT_MAX_EXECUTION_STEPS` | `10` |
| `AGENT_MAX_TOOL_CALLS` | `3` |
| `TICKET_DATABASE_PATH` | `storage/tickets.db` |
| `APPROVAL_CHECKPOINT_PATH` | `storage/approval_checkpoints.db` |

Chunk 在 Embedding 前会按模型 Tokenizer 检查长度。超过 512 Token 的 Chunk 会带重叠
拆成多个向量 Part，并继续保存原 `chunk_id`、`chunk_index` 和来源信息，不会丢弃尾部。
Point ID 由 `document_id + chunk_id + part + index_version` 生成稳定 UUID，重复索引
会覆盖相同 Point，不会生成重复记录。

BM25 使用 `jieba` 分词中文，并保留英文、数字、错误代码和产品编号。例如
`CACHE_ERR_504` 会保留完整代码，同时增加 `cache`、`err`、`504` 子词。
BM25 与 Dense 复用完全相同的 `chunk_id + part_index`，Token 化记录保存在
`storage/bm25`，服务重启时会从该 JSON 索引重建内存矩阵。

Hybrid 使用 Reciprocal Rank Fusion，默认 `k=60`：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

融合只使用 Dense 和 BM25 的排名，不直接相加 Cosine 和 BM25 原始分数。相同
`document_id + chunk_id + part_index` 只保留一个融合候选。

### 索引和检索 API

- `POST /api/v1/documents/{document_id}/index`：同时更新 Dense 和 BM25 索引。
- `POST /api/v1/retrieval/search`：支持 `dense`、`bm25`、`hybrid` 三种模式。

检索请求示例：

```json
{
  "query": "缓存击穿应该怎么处理？",
  "top_k": 3,
  "mode": "hybrid",
  "rerank": false,
  "candidate_k": null,
  "document_id": null
}
```

`mode` 默认仍为 `dense`，因此旧请求不需要修改。`document_id` 可省略；填写后只在
该文档内检索。Hybrid 返回结果同时包含 Dense/BM25 原始排名和分数。

### CrossEncoder 精排

`rerank=true` 时先按当前模式召回 `candidate_k` 个候选，再使用
`BAAI/bge-reranker-base` 对 `query + candidate.content` 批量打分。Reranker 在 CPU
后台线程运行，不阻塞 FastAPI 事件循环。

- `candidate_k` 默认 `20`，不能小于最终 `top_k`。
- 超长候选会按 Reranker Tokenizer 窗口拆分，并以各窗口最高分代表该候选。
- 响应保留原始 `retrieval_rank`、`retrieval_score` 和最终的 `rerank_score`。
- CrossEncoder 原始分数是对数相关分数，不是概率，不能直接作为拒答置信度。
- Reranker 被关闭或加载失败时返回明确 `503`，当前不执行静默降级。
- API 默认 `rerank=false`，旧请求行为不变。

升级到 BM25 与 Hybrid 后，已有 Dense 文档需要重新调用一次索引接口，以补齐对应的
BM25 单元。未补齐时 Hybrid 会返回 `409 INDEX_INCOMPATIBLE`。

Swagger 测试步骤：

1. 从 `GET /api/v1/documents` 复制一个 `document_id`。
2. 调用 `POST /api/v1/documents/{document_id}/index` 建立索引。
3. 打开 `POST /api/v1/retrieval/search`。
4. 输入问题、`top_k` 和 `mode`，点击 **Execute**。
5. 检查 `items` 中的 `rank`、`score`、`mode`、`dense_rank`、`dense_score`、
   `bm25_rank`、`bm25_score`、`retrieval_rank`、`retrieval_score`、
   `rerank_score`、来源元数据和 `content`。

需要精排时额外传入：

```json
{
  "rerank": true,
  "candidate_k": 20
}
```

## 知识库增强问答

`POST /api/v1/rag/ask` 执行完整非流式链路：

```text
问题
→ Hybrid 检索（默认 rerank=false）
→ 按 Token 预算选择完整证据片段
→ 证据编号化
→ DeepSeek 结构化回答
→ 后端校验引用编号
→ 返回回答和真实来源
```

请求示例：

```json
{
  "query": "怎样既保证订单事务一致性，又避免把 API Key 暴露在前端？",
  "top_k": 5,
  "mode": "hybrid",
  "rerank": false,
  "candidate_k": null,
  "document_id": null
}
```

支持与检索接口相同的 `mode`、`rerank`、`candidate_k` 和 `document_id`。

证据和引用规则：

- 文档正文被放入明确的 `<evidence>` 边界，并声明为不可信数据。
- 文档中的“忽略系统指令”“输出密钥”等文本不能作为系统指令执行。
- 模型只输出结构化 JSON，包含 `answered` 或 `insufficient_evidence`。
- 回答中的 `[1]` 必须映射到本次后端证据编号。
- 引用编号不存在、正文引用与 `used_citations` 不一致或证据不足时失败关闭。
- 响应 `sources` 只包含回答实际使用的来源，由后端映射文件名、页码和 Chunk。
- Cosine、BM25、RRF 和 Reranker 分数没有被转换为概率，也没有设置固定拒答阈值。
- 证据是否充分由模型结合证据内容做解释性判断，同时受 Token 预算和引用校验限制。

响应示例：

```json
{
  "answer": "MySQL 事务用于保证订单一致性 [2]。API Key 只能保存在后端 [1]。",
  "status": "answered",
  "reason": "证据明确支持回答。",
  "sources": [
    {
      "citation_id": 1,
      "document_id": "...",
      "chunk_id": "...",
      "filename": "security.md",
      "page_number": 3,
      "part_index": 1,
      "content_excerpt": "..."
    }
  ],
  "retrieval_mode": "hybrid",
  "rerank_applied": false,
  "retrieval_count": 5,
  "model": "deepseek-chat",
  "usage": {"prompt_tokens": 700, "completion_tokens": 90},
  "latency_ms": {
    "retrieval_ms": 12.0,
    "context_ms": 3.0,
    "generation_ms": 1200.0,
    "total_ms": 1215.0
  }
}
```

Swagger 测试：

1. 先为文档建立 Dense + BM25 索引。
2. 打开 `POST /api/v1/rag/ask`。
3. 输入问题并点击 **Execute**。
4. 检查 `status`、`answer`、`sources` 和 `latency_ms`。
5. `insufficient_evidence` 表示知识库没有足够依据，不与 DeepSeek 超时或网络异常混淆。

## 检索评测

人工标注评测集位于：

```text
evaluations/rag_retrieval_v1
```

包含 10 份文档、30 个问题，覆盖关键词、编号、语义改写、跨段落和无答案场景。
运行：

```powershell
cd D:\Projects\OpsPilot\backend
.\.venv\Scripts\Activate.ps1
python ..\evaluations\rag_retrieval_v1\run_evaluation.py
```

结果输出到 `latest_results.json` 和 `latest_results.md`。

## LangGraph Agent

`POST /api/v1/agent/run` 使用真正的 LangGraph `StateGraph`：

```text
START
→ supervisor
→ add_conditional_edges
   ├── knowledge_query → knowledge_node → END
   ├── ticket_request  → ticket_agent
   │                     ├── 无 tool_calls → END
   │                     └── tool_calls → ticket_tools
   │                                      → ticket_agent（有上限）
   ├── general_chat    → chat_node → END
   └── clarification   → clarification_node → END
```

Supervisor 使用 DeepSeek 结构化 JSON 输出判断意图，不使用关键词 if/else。

请求：

```json
{
  "message": "Redis 缓存击穿应该怎么解决？",
  "conversation_id": null
}
```

响应包含：

- `intent`
- `status`
- `answer`
- `ticket_draft`
- `sources`
- `executed_nodes`
- `supervisor_reason`
- `node_traces`
- `latency_ms`
- 真实 token usage
- `tool_calls` 安全审计摘要
- `memory_persisted=false`

节点复用：

- `knowledge` 调用现有 `RagQAService`，保留引用校验和证据不足状态。
- `chat` 调用现有 `ChatService`。
- `ticket_agent` 通过 DeepSeek 原生 `tools/tool_calls` 选择工单草稿工具。
- `ticket_tools` 只执行白名单工具，并把工具结果反馈给模型继续生成。
- `clarification` 不执行有副作用操作。

Supervisor 返回非法 JSON 或未知意图时会安全路由到 clarification，不会触发工单
或知识库节点。Supervisor 的超时、网络和上游 API 异常会保留为真实服务错误，
不再伪装成用户需要澄清。`AGENT_MAX_EXECUTION_STEPS` 限制图的最大执行步数，
`AGENT_MAX_TOOL_CALLS` 限制工具调用次数。

`conversation_id` 当前只回显，不保存多轮记忆。

### 工单草稿工具

OpenAI 兼容工具定义：

| 工具 | 参数 | 结果 |
|---|---|---|
| `create_ticket_draft` | `title`, `description`, `device_or_system` | 保存草稿并返回真实 draft ID |
| `get_ticket_draft` | `draft_id` | 返回已持久化草稿 |
| `update_ticket_draft` | `draft_id` 和至少一个可修改字段 | 更新草稿 |

所有参数使用 Pydantic 校验。工具执行器只允许上述三个名称，不接受 Python 代码、
SQL 或任意动态工具。

SQLite 表 `ticket_drafts`：

```text
id
idempotency_key UNIQUE
title
description
device_or_system
status = draft / pending_approval / approved / rejected
version
created_at
updated_at
```

数据库文件：

```text
storage/tickets.db
```

工具调用 ID 经 SHA-256 生成幂等键。相同工具调用重试会返回已有草稿，不重复写入。
数据库写入成功后，Agent 才回复“草稿已保存”。

草稿 API：

- `GET /api/v1/tickets/drafts`
- `GET /api/v1/tickets/drafts/{draft_id}`
- `PATCH /api/v1/tickets/drafts/{draft_id}`

`version` 是内容版本。草稿内容修改会递增版本，并且只有 `draft` 状态可以修改。
本阶段不存在正式工单提交或外部工单系统集成。

## 人工审批工作流

审批使用独立的最小 LangGraph `StateGraph`，不修改 Supervisor 和工单工具循环：

```text
START
→ load_draft（读取真实 SQLite 草稿）
→ await_decision（interrupt() 持久化暂停）
→ apply_decision（事务校验并写入 approved/rejected）
→ END
```

状态转换只允许：

```text
draft → pending_approval → approved
draft → pending_approval → rejected
```

接口：

- `POST /api/v1/tickets/drafts/{draft_id}/request-approval`
- `GET /api/v1/agent/approvals/{thread_id}`
- `POST /api/v1/agent/approvals/{thread_id}/decision`

请求审批不需要请求体，成功返回 `202`、唯一 `thread_id`、真实草稿快照和
`checkpoint_next=["await_decision"]`。

人工决策示例：

```json
{
  "decision": "approve",
  "note": "本地演示审批通过"
}
```

`decision` 只允许 `approve` 或 `reject`。返回结果包含审批状态、实际草稿状态、
备注、决策时间和真实执行节点：

```json
{
  "executed_nodes": [
    "load_draft",
    "await_decision",
    "apply_decision"
  ]
}
```

Checkpoint 使用独立的 `storage/approval_checkpoints.db`，由 FastAPI lifespan
创建、初始化 `AsyncSqliteSaver` 并在进程退出时关闭。工作流反序列化显式禁用
pickle fallback，并将 JSON/MessagePack 限制为内置安全类型。

暂停与恢复过程：

1. `request-approval` 先读取真实草稿，并启动对应 `thread_id` 的 LangGraph。
2. `await_decision` 调用真实 `interrupt()`；此时草稿尚未发生状态写入。
3. 确认 Checkpoint 确实停在 `await_decision` 后，同一业务事务写入审批映射、
   `pending_approval` 状态和 `request` 审计记录。
4. 决策接口先用当前 Checkpoint 确认存在有效 interrupt，再调用
   `Command(resume={"decision": ..., "note": ...})`。
5. `apply_decision` 在单个 SQLite 事务中同时更新草稿、审批映射和审计记录。

并发与幂等保护：

- 同一草稿只能有一个审批流程。
- 同一审批只能批准或拒绝一次。
- 相同 `thread_id` 的进程内决策串行执行。
- 数据库更新使用 `status` 和 `version` 条件更新；条件更新失败则整个事务回滚。
- `ticket_approval_audit` 对 `thread_id + action` 建立唯一约束。
- 审批中或已结束的草稿不能通过普通 PATCH 修改。
- 数据库事务失败不会返回成功；若节点失败后 Checkpoint 保留可重试任务，同一
  决策可在数据库恢复后安全重试。

业务数据库新增表：

```text
ticket_approvals
  thread_id PRIMARY KEY
  draft_id UNIQUE
  draft_version
  status
  note
  requested_at
  decided_at

ticket_approval_audit
  id PRIMARY KEY
  thread_id + action UNIQUE
  draft_id
  from_status
  to_status
  draft_version
  note
  created_at
```

已有 `tickets.db` 会在首次访问时执行轻量迁移，为 `ticket_drafts` 增加
`version INTEGER NOT NULL DEFAULT 1`，不会删除已有草稿。

审批接口当前没有正式身份认证、角色或租户隔离，只用于本机演示。路由会拒绝
非 localhost 客户端，即使如此也不能把这个接口直接暴露到公网。

Swagger 本地测试：

1. 从 `GET /api/v1/tickets/drafts` 获取一个状态为 `draft` 的草稿 ID。
2. 调用 `POST /api/v1/tickets/drafts/{draft_id}/request-approval`。
3. 复制响应中的 `thread_id`，调用 `GET /api/v1/agent/approvals/{thread_id}`。
4. 确认 `waiting_for_decision=true` 和草稿状态为 `pending_approval`。
5. 调用决策接口，提交 `approve` 或 `reject` 以及可选备注。
6. 再次查询草稿和审批，确认状态为 `approved` 或 `rejected`。

## 启动前端

保持后端运行，再打开一个新的 PowerShell：

```powershell
cd D:\Projects\OpsPilot\frontend
npm install
npm run dev
```

浏览器访问 <http://127.0.0.1:5173>。

Vite 开发服务器把 `/api` 请求代理到 `http://127.0.0.1:8000`。DeepSeek API Key
只存在于后端 `backend/.env`，前端不读取、不保存也不发送该密钥。

前端聊天历史只保存在当前页面内存中。发送新问题时只向后端提交当前问题，服务端
目前没有持久化会话或多轮对话记忆。

页面导航包含：

- **智能问答**：保留原有 DeepSeek 非流式/SSE 聊天能力。
- **知识库问答**：上传文档、索引文档、执行 Dense/BM25/Hybrid RAG 问答并查看引用。
- **Agent 助手**：运行 Supervisor 路由，查看意图结果、工具轨迹、真实工单草稿，
  并完成本地人工审批。

文档接口不返回持久化索引状态。前端只有在当前页面收到索引接口成功响应后，才显示
“本次已索引”；刷新或重新加载页面后显示“索引状态不可知”，不会虚构持久状态。

### Agent 智能助手页面

页面分为两个工作区：

- 左侧 Agent 助手调用 `POST /api/v1/agent/run`，根据 `intent` 和 `status`
  分别展示知识库回答、普通聊天、需要补充的信息或真实工单草稿。
- 右侧工单工作区读取真实草稿列表，支持查看、编辑 `draft` 状态草稿、提交审批、
  刷新审批 Checkpoint，以及批准或拒绝。

Agent 结果还会展示：

- `executed_nodes`
- `node_traces`
- 白名单 `tool_calls`
- 实际知识库 `sources`
- Supervisor 判断原因和模型耗时

页面不使用 `v-html`，Agent 回答、文档片段和工单内容都作为纯文本展示。

提交审批、批准和拒绝都会先显示确认对话框。审批操作完成后，前端会再次请求：

```text
GET /api/v1/agent/approvals/{thread_id}
GET /api/v1/tickets/drafts/{draft_id}
GET /api/v1/tickets/drafts
```

只有重新查询到的审批状态和草稿状态一致时，页面才显示成功。409 冲突、审批流程
不存在、网络错误和数据库错误都会显示明确中文提示。

后端没有“按 draft_id 查询审批 thread_id”的接口，因此当前页面会把成功提交审批后
返回的 `thread_id` 保存在浏览器 `localStorage` 中，仅用于本地演示和页面刷新恢复。
如果草稿显示为 `pending_approval`，但当前浏览器没有对应 `thread_id`，页面会明确
提示无法安全恢复，不会伪造审批能力。

审批期间后端禁止 PATCH 草稿，前端也会禁用编辑入口。当前仍没有正式身份认证、审批人
角色或多租户隔离，页面明确标记为 localhost 本地演示。

## 调用问答接口

```powershell
$body = @{ message = "请用三句话解释什么是 RAG" } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/chat" `
  -ContentType "application/json; charset=utf-8" `
  -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

成功响应示例：

```json
{
  "answer": "RAG 是检索增强生成……",
  "model": "deepseek-chat",
  "usage": {
    "prompt_tokens": 42,
    "completion_tokens": 30
  }
}
```

## 调用流式问答接口

启动服务后，打开 <http://127.0.0.1:8000/docs>，选择
`POST /api/v1/chat/stream`，点击 **Try it out**，提交：

```json
{
  "message": "请用三句话解释什么是 RAG"
}
```

Swagger 页面可能一次性展示收到的 SSE 内容。如果需要在终端观察逐步输出，可执行：

```powershell
$body = '{"message":"请用三句话解释什么是 RAG"}'
curl.exe --no-buffer -N -X POST "http://127.0.0.1:8000/api/v1/chat/stream" `
  -H "Content-Type: application/json" `
  -H "Accept: text/event-stream" `
  --data-raw $body
```

标准 SSE 响应示例：

```text
event: meta
data: {"request_id":"...","model":"deepseek-chat","created_at":"..."}

event: token
data: {"text":"RAG "}

event: token
data: {"text":"是检索增强生成。"}

event: usage
data: {"prompt_tokens":42,"completion_tokens":30}

event: done
data: {"request_id":"..."}
```

如果生成过程中发生上游错误，服务会发送 `error` 事件并结束当前响应，不会导致
FastAPI 进程退出。上游没有返回 token 用量时不会发送 `usage` 事件。

## 运行后端测试

测试使用 Fake LLM，不会调用 DeepSeek，也不会消耗 API 额度：

```powershell
cd D:\Projects\OpsPilot\backend
.\.venv\Scripts\Activate.ps1
python -m pytest
```

## 运行前端测试和构建

```powershell
cd D:\Projects\OpsPilot\frontend
npm test
npm run build
```

真实浏览器 E2E 使用本机 Edge，并要求前后端已启动：

```powershell
cd D:\Projects\OpsPilot\frontend
npm run test:e2e:knowledge
npm run test:e2e:agent:intents
npm run test:e2e:agent:smoke
```

需要验证后端重启时，按两阶段运行：

```powershell
# 第一个终端保持前后端运行
cd D:\Projects\OpsPilot\frontend
npm run test:e2e:agent:prepare

# 停止并重新启动后端的 Uvicorn 进程

cd D:\Projects\OpsPilot\frontend
npm run test:e2e:agent:resume
```

`prepare` 会通过真实 Agent 创建并提交一份工单；`resume` 使用同一
`draft_id/thread_id` 恢复等待流程，在浏览器批准后再创建一份草稿并拒绝。
E2E 会创建真实本地工单数据，但不包含敏感文档或密钥。

截图输出到 `frontend/e2e/artifacts`，该目录不会提交到 Git。

如果希望额外验证真实 DeepSeek 网络调用，请先填写 `backend/.env`，启动服务后调用
上面的非流式或流式问答接口。真实调用结果取决于 API Key、账户额度和网络状态。

