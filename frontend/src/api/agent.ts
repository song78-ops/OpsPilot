import type {
  AgentRunResponse,
  ApprovalDecisionRequest,
  ApprovalDecisionResponse,
  ApprovalDetailResponse,
  TicketDraft,
  TicketDraftListResponse,
  TicketDraftUpdateRequest,
} from '../types/agent'

interface ErrorBody {
  error?: {
    code?: string
    message?: string
  }
  detail?: string | Array<{ msg?: string }>
}

const ERROR_MESSAGES: Record<string, string> = {
  AGENT_NODE_ERROR: 'Agent 工作流执行失败，请稍后重试。',
  TOOL_CALL_LIMIT: '工具调用次数达到限制，请补充信息后重新发起。',
  SUPERVISOR_INVALID_OUTPUT: '意图识别结果无效，请换一种方式描述问题。',
  LLM_TIMEOUT: '模型响应超时，请稍后重试。',
  LLM_CONNECTION_ERROR: '无法连接模型服务，请检查网络。',
  LLM_UPSTREAM_ERROR: '模型服务返回异常，请稍后重试。',
  CONFIGURATION_ERROR: '服务端尚未完成必要的模型配置。',
  TICKET_DRAFT_NOT_FOUND: '工单草稿不存在或已经被移除。',
  TICKET_DRAFT_STATE_CONFLICT: '草稿当前状态不允许修改或提交审批。',
  TICKET_DRAFT_VERSION_CONFLICT: '草稿内容已变化，请刷新后重新审批。',
  TICKET_APPROVAL_NOT_FOUND: '审批流程不存在，或本地记录的流程 ID 已失效。',
  TICKET_APPROVAL_STATE_CONFLICT: '该审批已经处理，不能重复批准或拒绝。',
  APPROVAL_CHECKPOINT_STATE_INVALID: '审批 Checkpoint 与业务状态不一致，请检查后端数据。',
  APPROVAL_WORKFLOW_ERROR: '审批工作流恢复失败，请检查后端服务。',
  APPROVAL_LOCAL_ONLY: '审批接口只允许从本机 localhost 访问。',
  TICKET_PERSISTENCE_ERROR: '工单或审批数据写入失败，请稍后重试。',
  NETWORK_ERROR: '无法连接后端服务，请确认 Vite 代理和 FastAPI 已启动。',
}

export class AgentApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message)
    this.name = 'AgentApiError'
  }
}

function parseMessage(body: ErrorBody, status: number): { message: string; code: string } {
  const code = body.error?.code ?? 'HTTP_ERROR'
  const detailMessage = Array.isArray(body.detail)
    ? body.detail[0]?.msg
    : body.detail
  return {
    code,
    message: ERROR_MESSAGES[code]
      ?? body.error?.message
      ?? detailMessage
      ?? `请求失败（HTTP ${status}）。`,
  }
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(input, init)
  } catch {
    throw new AgentApiError(
      ERROR_MESSAGES.NETWORK_ERROR,
      0,
      'NETWORK_ERROR',
    )
  }
  if (!response.ok) {
    let body: ErrorBody = {}
    try {
      body = (await response.json()) as ErrorBody
    } catch {
      // Keep the Chinese HTTP fallback when the server returns non-JSON.
    }
    const parsed = parseMessage(body, response.status)
    throw new AgentApiError(parsed.message, response.status, parsed.code)
  }
  return (await response.json()) as T
}

function jsonInit(method: string, payload: unknown): RequestInit {
  return {
    method,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  }
}

export async function runAgent(
  message: string,
  conversationId?: string | null,
): Promise<AgentRunResponse> {
  return requestJson<AgentRunResponse>(
    '/api/v1/agent/run',
    jsonInit('POST', {
      message,
      conversation_id: conversationId ?? null,
    }),
  )
}

export async function listTicketDrafts(): Promise<TicketDraftListResponse> {
  return requestJson<TicketDraftListResponse>('/api/v1/tickets/drafts')
}

export async function getTicketDraft(draftId: string): Promise<TicketDraft> {
  return requestJson<TicketDraft>(`/api/v1/tickets/drafts/${draftId}`)
}

export async function updateTicketDraft(
  draftId: string,
  payload: TicketDraftUpdateRequest,
): Promise<TicketDraft> {
  return requestJson<TicketDraft>(
    `/api/v1/tickets/drafts/${draftId}`,
    jsonInit('PATCH', payload),
  )
}

export async function requestTicketApproval(draftId: string): Promise<ApprovalDetailResponse> {
  return requestJson<ApprovalDetailResponse>(
    `/api/v1/tickets/drafts/${draftId}/request-approval`,
    { method: 'POST' },
  )
}

export async function getTicketApproval(threadId: string): Promise<ApprovalDetailResponse> {
  return requestJson<ApprovalDetailResponse>(
    `/api/v1/agent/approvals/${threadId}`,
  )
}

export async function decideTicketApproval(
  threadId: string,
  payload: ApprovalDecisionRequest,
): Promise<ApprovalDecisionResponse> {
  return requestJson<ApprovalDecisionResponse>(
    `/api/v1/agent/approvals/${threadId}/decision`,
    jsonInit('POST', payload),
  )
}
