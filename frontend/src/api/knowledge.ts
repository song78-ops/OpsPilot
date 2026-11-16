import type {
  DocumentDetail,
  DocumentIndexResponse,
  DocumentListResponse,
  RagAskRequest,
  RagAskResponse,
} from '../types/knowledge'

interface ErrorBody {
  error?: {
    code?: string
    message?: string
  }
  detail?: string | Array<{ msg?: string }>
}

const ERROR_MESSAGES: Record<string, string> = {
  UNSUPPORTED_DOCUMENT_TYPE: '文件格式不受支持，请选择 PDF、DOCX、TXT 或 Markdown。',
  DOCUMENT_TOO_LARGE: '文件超过服务端大小限制。',
  DOCUMENT_VALIDATION_ERROR: '文件校验失败，请检查文件是否为空或文件名是否合法。',
  DOCUMENT_PARSE_ERROR: '无法提取文档文字。扫描 PDF 请先完成 OCR。',
  DOCUMENT_NOT_FOUND: '文档不存在或已经被移除。',
  DOCUMENT_NOT_INDEXED: '该文档尚未加入知识库，请先完成处理。',
  INDEX_INCOMPATIBLE: '知识库需要更新，请重新处理文档。',
  VECTOR_STORE_UNAVAILABLE: '知识库服务暂时不可用，请稍后重试。',
  EMBEDDING_UNAVAILABLE: '知识检索服务暂时不可用，请稍后重试。',
  RERANKER_UNAVAILABLE: '结果精排暂时不可用，请关闭高级设置中的精排后重试。',
  QUERY_TOKEN_LIMIT_EXCEEDED: '问题过长，超过检索模型限制。',
  INVALID_RETRIEVAL_PARAMETER: '检索设置不合法，请检查高级设置。',
  LLM_TIMEOUT: '模型响应超时，请稍后重试。',
  LLM_CONNECTION_ERROR: '无法连接模型服务，请检查网络。',
  LLM_UPSTREAM_ERROR: '模型服务返回异常，请稍后重试。',
  CONFIGURATION_ERROR: '服务端尚未完成模型配置。',
}

export class KnowledgeApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message)
    this.name = 'KnowledgeApiError'
  }
}

function messageFromBody(body: ErrorBody, status: number): { message: string; code: string } {
  const code = body.error?.code ?? 'HTTP_ERROR'
  const detailMessage = Array.isArray(body.detail)
    ? body.detail[0]?.msg
    : body.detail
  const fallback = body.error?.message
    ?? detailMessage
    ?? `请求失败（HTTP ${status}）。`
  return {
    code,
    message: ERROR_MESSAGES[code] ?? fallback,
  }
}

async function parseError(response: Response): Promise<KnowledgeApiError> {
  let body: ErrorBody = {}
  try {
    body = (await response.json()) as ErrorBody
  } catch {
    // Fall back to the HTTP status and a Chinese generic message.
  }
  const parsed = messageFromBody(body, response.status)
  return new KnowledgeApiError(parsed.message, response.status, parsed.code)
}

async function requestJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(input, init)
  } catch {
    throw new KnowledgeApiError(
      '无法连接服务，请确认系统已启动后重试。',
      0,
      'NETWORK_ERROR',
    )
  }
  if (!response.ok) {
    throw await parseError(response)
  }
  return (await response.json()) as T
}

export async function listDocuments(): Promise<DocumentListResponse> {
  return requestJson<DocumentListResponse>('/api/v1/documents')
}

export async function uploadDocument(file: File): Promise<DocumentDetail> {
  const form = new FormData()
  form.append('file', file, file.name)
  return requestJson<DocumentDetail>('/api/v1/documents/upload', {
    method: 'POST',
    body: form,
  })
}

export async function indexDocument(documentId: string): Promise<DocumentIndexResponse> {
  return requestJson<DocumentIndexResponse>(
    `/api/v1/documents/${documentId}/index`,
    { method: 'POST' },
  )
}

export async function askKnowledgeBase(payload: RagAskRequest): Promise<RagAskResponse> {
  return requestJson<RagAskResponse>('/api/v1/rag/ask', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

