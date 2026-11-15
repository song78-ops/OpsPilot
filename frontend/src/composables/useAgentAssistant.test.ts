import { afterEach, describe, expect, it, vi } from 'vitest'

import { AgentApiError, runAgent } from '../api/agent'
import type {
  AgentIntent,
  AgentRunResponse,
  AgentStatus,
  TicketDraft,
} from '../types/agent'
import { useAgentAssistant } from './useAgentAssistant'

vi.mock('../api/agent', () => ({
  runAgent: vi.fn(),
  AgentApiError: class extends Error {
    constructor(
      message: string,
      readonly status = 0,
      readonly code = 'ERROR',
    ) {
      super(message)
      this.name = 'AgentApiError'
    }
  },
}))

const draft: TicketDraft = {
  id: 'a'.repeat(32),
  title: '电脑无法联网',
  description: '办公电脑无法连接公司网络。',
  device_or_system: 'Windows 笔记本',
  status: 'draft',
  version: 1,
  created_at: '2026-11-15T00:00:00Z',
  updated_at: '2026-11-15T00:00:00Z',
}

function response(
  intent: AgentIntent,
  status: AgentStatus,
): AgentRunResponse {
  return {
    intent,
    status,
    answer: `回答：${intent}`,
    ticket_draft: intent === 'ticket_request' ? draft : null,
    sources: [],
    executed_nodes: ['supervisor'],
    supervisor_reason: '测试路由',
    model: 'fake-deepseek',
    usage: null,
    error: null,
    latency_ms: 10,
    node_traces: [],
    tool_calls: [],
    conversation_id: null,
    memory_persisted: false,
  }
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('useAgentAssistant', () => {
  it.each([
    ['knowledge_query', 'completed'],
    ['general_chat', 'completed'],
    ['clarification', 'needs_clarification'],
    ['ticket_request', 'ticket_draft_ready'],
  ] as const)(
    'keeps the %s intent result for UI rendering',
    async (intent, status) => {
      vi.mocked(runAgent).mockResolvedValue(response(intent, status))
      const assistant = useAgentAssistant()
      assistant.question.value = '测试请求'

      const result = await assistant.run()

      expect(result?.intent).toBe(intent)
      expect(assistant.result.value?.status).toBe(status)
      if (intent === 'ticket_request') {
        expect(assistant.result.value?.ticket_draft?.id).toBe(draft.id)
      }
      expect(assistant.question.value).toBe('')
    },
  )

  it('shows a Chinese Agent service error without a fake result', async () => {
    vi.mocked(runAgent).mockRejectedValue(
      new AgentApiError('模型响应超时，请稍后重试。', 504, 'LLM_TIMEOUT'),
    )
    const assistant = useAgentAssistant()
    assistant.question.value = '创建工单'

    await assistant.run()

    expect(assistant.error.value).toContain('模型响应超时')
    expect(assistant.result.value).toBeNull()
  })

  it('prevents duplicate runs while a request is active', async () => {
    let resolveRequest: ((value: AgentRunResponse) => void) | undefined
    vi.mocked(runAgent).mockImplementation(
      () => new Promise((resolve) => {
        resolveRequest = resolve
      }),
    )
    const assistant = useAgentAssistant()
    assistant.question.value = '你好'

    const first = assistant.run()
    const second = assistant.run()

    expect(runAgent).toHaveBeenCalledTimes(1)
    resolveRequest?.(response('general_chat', 'completed'))
    await Promise.all([first, second])
  })
})
