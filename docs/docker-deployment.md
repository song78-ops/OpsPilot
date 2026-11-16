# OpsPilot Docker 本地部署

该 Compose 仅用于单机演示。前端只监听宿主机 `127.0.0.1:8080`，后端只在
Compose 内部网络监听 `8000`，不开放公网端口。

## 前置条件

- Docker Desktop
- Docker Compose v2
- 可用的本地 `storage` 目录

默认使用本地 Mock，不需要 API Key：

```powershell
cd D:\Projects\OpsPilot
docker compose up --build -d
docker compose ps
```

浏览器访问 <http://127.0.0.1:8080>。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/healthz
Invoke-RestMethod http://127.0.0.1:8080/api/v1/health
docker compose logs -f backend
```

## 持久化目录

宿主机 `storage` 挂载到容器 `/app/storage`，包括：

```text
storage/documents
storage/models
storage/qdrant
storage/bm25
storage/tickets.db
storage/conversations.db
storage/approval_checkpoints.db
```

容器重启或重建后数据仍保留。BGE/Reranker 权重不进入镜像；可提前放到
`storage/models`，或通过容器脚本下载：

```powershell
docker compose run --rm backend python scripts/download_bge_model.py
docker compose run --rm backend python scripts/download_reranker_model.py
```

## 可选真实 DeepSeek

在未跟踪的项目根目录 `.env` 中设置环境变量，或在当前 PowerShell 会话中设置。
不要提交 `.env`：

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key
REAL_LLM_MAX_REQUESTS=20
REAL_LLM_MAX_TOKENS=50000
REAL_LLM_MAX_COST_USD=1.00
REAL_LLM_MAX_OUTPUT_TOKENS=1024
REAL_LLM_INPUT_COST_PER_MILLION_USD=your_input_rate
REAL_LLM_OUTPUT_COST_PER_MILLION_USD=your_output_rate
```

Compose 只通过运行时环境变量注入这些值，不写入镜像。

## 审批接口安全

Nginx 固定使用 `172.30.240.10`，后端只信任该地址发送的代理转发头。Nginx 会
覆盖客户端的 `X-Real-IP` 和 `X-Forwarded-For`，因此 FastAPI 仍能执行原有
localhost 校验。不要为排查联通问题而删除后端 localhost 校验或信任任意代理。

如本机已有子网使用 `172.30.240.0/24`，需要同时修改 Compose 子网、Nginx 固定
地址和后端 `--forwarded-allow-ips`，三处必须保持一致。

## 运维

```powershell
# 重启
docker compose restart

# 查看状态
docker compose ps

# 停止
docker compose down

# 重新构建并启动
docker compose up --build -d
```

`docker compose down` 不会删除宿主机 `storage`。不要将后端发布为
`0.0.0.0:8000` 或把前端端口改为公网地址。
