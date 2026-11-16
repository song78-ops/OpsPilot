import type { RagSource, TokenUsage } from './knowledge'

export type AgentIntent =
  | 'knowledge_query'
  | 'ticket_request'
  | 'general_chat'
  | 'clarification'

export type AgentStatus =
  | 'completed'
  | 'insufficient_evidence'
  | 'ticket_draft_ready'
  | 'needs_clarification'

export type TicketDraftStatus =
  | 'draft'
  | 'pending_approval'
  | 'approved'
  | 'rejected'

export type ApprovalStatus = 'pending_approval' | 'approved' | 'rejected'
export type DraftApprovalStatus =
  | 'not_requested'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
export type ApprovalDecision = 'approve' | 'reject'

export interface TicketDraft {
  id: string
  title: string
  description: string
  device_or_system: string
  status: TicketDraftStatus
  version: number
  created_at: string
  updated_at: string
}

export interface TicketDraftListResponse {
  items: TicketDraft[]
  total: number
}

export interface TicketDraftUpdateRequest {
  title?: string
  description?: string
  device_or_system?: string
}

export interface AgentNodeTrace {
  node: string
  duration_ms: number
  status: string
  error: string | null
}

export interface AgentToolCall {
  tool_call_id: string
  name: string
  status: string
  duration_ms: number
  error: string | null
}

export interface AgentRunResponse {
  intent: AgentIntent
  status: AgentStatus
  answer: string | null
  ticket_draft: TicketDraft | null
  sources: RagSource[]
  executed_nodes: string[]
  supervisor_reason: string
  model: string | null
  usage: TokenUsage | null
  error: string | null
  latency_ms: number
  node_traces: AgentNodeTrace[]
  tool_calls: AgentToolCall[]
  conversation_id: string | null
  memory_persisted: boolean
  request_id?: string | null
  idempotent_replay?: boolean
}

export type ConversationMessageRole = 'user' | 'assistant' | 'tool'

export interface ConversationSummary {
  conversation_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationListResponse {
  items: ConversationSummary[]
  total: number
  limit: number
  offset: number
}

export interface ConversationMessage {
  id: number
  role: ConversationMessageRole
  content: string
  intent: AgentIntent | null
  status: string | null
  tool_name: string | null
  tool_status: string | null
  business_reference_id: string | null
  created_at: string
}

export interface ConversationHistoryResponse {
  conversation_id: string
  created_at: string
  updated_at: string
  last_ticket_draft_id: string | null
  ticket_references: string[]
  total: number
  messages: ConversationMessage[]
  memory_persisted: true
}

export interface ApprovalRecord {
  thread_id: string
  draft_id: string
  draft_version: number
  status: ApprovalStatus
  note: string | null
  requested_at: string
  decided_at: string | null
}

export interface ApprovalDetailResponse {
  approval: ApprovalRecord
  draft: TicketDraft
  waiting_for_decision: boolean
  checkpoint_next: string[]
}

export interface DraftApprovalLookupResponse {
  draft: TicketDraft
  approval: ApprovalRecord | null
  status: DraftApprovalStatus
  waiting_for_decision: boolean
  checkpoint_next: string[]
}

export interface ApprovalDecisionRequest {
  decision: ApprovalDecision
  note?: string | null
}

export interface ApprovalDecisionResponse {
  approval: ApprovalRecord
  draft: TicketDraft
  decision: ApprovalDecision
  executed_nodes: string[]
  waiting_for_decision: false
}
