import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  AgentApiError,
  getAgentConversationHistory,
  listAgentConversations,
  runAgent,
} from '../api/agent'
import type {
  AgentIntent,
  AgentRunResponse,
  AgentStatus,
  ConversationHistoryResponse,
  ConversationSummary,
  TicketDraft,
} from '../types/agent'
import { useAgentAssistant } from './useAgentAssistant'

vi.mock('../api/agent', () => ({
  runAgent: vi.fn(),
  listAgentConversations: vi.fn(),
  getAgentConversationHistory: vi.fn(),
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

const firstConversationId = '1'.repeat(32)
const secondConversationId = '2'.repeat(32)

function conversation(
  id: string,
  title: string,
  updatedAt: string,
): ConversationSummary {
  return {
    conversation_id: id,
    title,
    created_at: '2026-11-15T00:00:00Z',
    updated_at: updatedAt,
  }
}

function response(
  intent: AgentIntent,
  status: AgentStatus,
  conversationId = firstConversationId,
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
    conversation_id: conversationId,
    memory_persisted: true,
  }
}

function history(
  conversationId: string,
  userContent = '历史用户消息',
  assistantContent = '历史助手回答',
): ConversationHistoryResponse {
  return {
    conversation_id: conversationId,
    created_at: '2026-11-15T00:00:00Z',
    updated_at: '2026-11-15T00:05:00Z',
    last_ticket_draft_id: null,
    ticket_references: [],
    total: 2,
    messages: [
      {
        id: 1,
        role: 'user',
        content: userContent,
        intent: null,
        status: null,
        tool_name: null,
        tool_status: null,
        business_reference_id: null,
        created_at: '2026-11-15T00:00:00Z',
      },
      {
        id: 2,
        role: 'assistant',
        content: assistantContent,
        intent: 'general_chat',
        status: 'completed',
        tool_name: null,
        tool_status: null,
        business_reference_id: null,
        created_at: '2026-11-15T00:01:00Z',
      },
    ],
    memory_persisted: true,
  }
}

function memoryStorage(initial?: [string, string]) {
  const values = new Map<string, string>()
  if (initial) {
    values.set(...initial)
  }
  return {
    values,
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  }
}

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('useAgentAssistant', () => {
  it.each([
    ['knowledge_query', 'completed'],
    ['general_chat', 'completed'],
    ['clarification', 'needs_clarification'],
    ['ticket_request', 'ticket_draft_ready'],
  ] as const)(
    'keeps the %s intent and reloads server history',
    async (intent, status) => {
      vi.mocked(runAgent).mockResolvedValue(response(intent, status))
      vi.mocked(getAgentConversationHistory).mockResolvedValue(
        history(firstConversationId),
      )
      vi.mocked(listAgentConversations).mockResolvedValue({
        items: [conversation(firstConversationId, '历史用户消息', '2026-11-15T00:05:00Z')],
        total: 1,
        limit: 30,
        offset: 0,
      })
      const assistant = useAgentAssistant()
      assistant.question.value = '测试请求'

      const result = await assistant.run()

      expect(result?.intent).toBe(intent)
      expect(assistant.latestResult.value?.status).toBe(status)
      expect(assistant.currentConversationId.value).toBe(firstConversationId)
      expect(assistant.messages.value).toHaveLength(2)
      expect(runAgent).toHaveBeenCalledWith(
        '测试请求',
        null,
        expect.any(String),
      )
      expect(assistant.question.value).toBe('')
    },
  )

  it('reuses the server conversation id on the next message', async () => {
    vi.mocked(runAgent)
      .mockResolvedValueOnce(response('general_chat', 'completed'))
      .mockResolvedValueOnce(response('general_chat', 'completed'))
    vi.mocked(getAgentConversationHistory).mockResolvedValue(
      history(firstConversationId),
    )
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [conversation(firstConversationId, '你好', '2026-11-15T00:05:00Z')],
      total: 1,
      limit: 30,
      offset: 0,
    })
    const assistant = useAgentAssistant()

    assistant.question.value = '你好'
    await assistant.send()
    assistant.question.value = '继续'
    await assistant.send()

    expect(vi.mocked(runAgent).mock.calls).toEqual([
      ['你好', null, expect.any(String)],
      ['继续', firstConversationId, expect.any(String)],
    ])
  })

  it('restores the saved conversation from server history', async () => {
    const storage = memoryStorage([
      'opspilot.agent.lastConversationId',
      firstConversationId,
    ])
    vi.stubGlobal('localStorage', storage)
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [
        conversation(secondConversationId, '最新会话', '2026-11-15T02:00:00Z'),
        conversation(firstConversationId, '上次会话', '2026-11-15T01:00:00Z'),
      ],
      total: 2,
      limit: 30,
      offset: 0,
    })
    vi.mocked(getAgentConversationHistory).mockResolvedValue(
      history(firstConversationId, '上次的问题', '上次的回答'),
    )
    const assistant = useAgentAssistant()

    await assistant.restore()

    expect(assistant.currentConversationId.value).toBe(firstConversationId)
    expect(assistant.messages.value[0].content).toBe('上次的问题')
    expect(assistant.messages.value[1].content).toBe('上次的回答')
  })

  it('falls back to the newest server conversation when cache is stale', async () => {
    const storage = memoryStorage([
      'opspilot.agent.lastConversationId',
      'f'.repeat(32),
    ])
    vi.stubGlobal('localStorage', storage)
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [
        conversation(secondConversationId, '最新会话', '2026-11-15T02:00:00Z'),
      ],
      total: 1,
      limit: 30,
      offset: 0,
    })
    vi.mocked(getAgentConversationHistory)
      .mockRejectedValueOnce(
        new AgentApiError('会话不存在', 404, 'CONVERSATION_NOT_FOUND'),
      )
      .mockResolvedValueOnce(history(secondConversationId, '最新问题', '最新回答'))
    const assistant = useAgentAssistant()

    await assistant.restore()

    expect(assistant.currentConversationId.value).toBe(secondConversationId)
    expect(assistant.messages.value[0].content).toBe('最新问题')
    expect(storage.values.get('opspilot.agent.lastConversationId')).toBe(
      secondConversationId,
    )
  })

  it('replaces all temporary state when switching conversations', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [
        conversation(firstConversationId, '会话一', '2026-11-15T01:00:00Z'),
        conversation(secondConversationId, '会话二', '2026-11-15T02:00:00Z'),
      ],
      total: 2,
      limit: 30,
      offset: 0,
    })
    vi.mocked(getAgentConversationHistory)
      .mockResolvedValueOnce(history(firstConversationId, '会话一用户', '会话一回答'))
      .mockResolvedValueOnce(history(firstConversationId, '会话一用户', '会话一回答'))
      .mockResolvedValueOnce(history(secondConversationId, '会话二用户', '会话二回答'))
    vi.mocked(runAgent).mockResolvedValue(
      response('general_chat', 'completed'),
    )
    const assistant = useAgentAssistant()
    await assistant.restore()
    assistant.question.value = '继续'
    await assistant.send()
    expect(assistant.latestResult.value).not.toBeNull()

    await assistant.selectConversation(secondConversationId)

    expect(assistant.currentConversationId.value).toBe(secondConversationId)
    expect(assistant.latestResult.value).toBeNull()
    expect(assistant.messages.value.map((item) => item.content)).toEqual([
      '会话二用户',
      '会话二回答',
    ])
  })

  it('new conversation clears history and stores no chat content', async () => {
    const storage = memoryStorage([
      'opspilot.agent.lastConversationId',
      firstConversationId,
    ])
    vi.stubGlobal('localStorage', storage)
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [
        conversation(firstConversationId, '会话一', '2026-11-15T01:00:00Z'),
      ],
      total: 1,
      limit: 30,
      offset: 0,
    })
    vi.mocked(getAgentConversationHistory).mockResolvedValue(
      history(firstConversationId),
    )
    const assistant = useAgentAssistant()
    await assistant.restore()

    assistant.startNewConversation()

    expect(assistant.currentConversationId.value).toBeNull()
    expect(assistant.messages.value).toEqual([])
    expect(storage.values.has('opspilot.agent.lastConversationId')).toBe(false)
    expect([...storage.values.values()].join(' ')).not.toContain('历史')
  })

  it('shows a network error without fabricating messages', async () => {
    vi.mocked(runAgent).mockRejectedValue(
      new AgentApiError('网络中断', 0, 'NETWORK_ERROR'),
    )
    const assistant = useAgentAssistant()
    assistant.question.value = '创建工单'

    const result = await assistant.send()

    expect(result).toBeNull()
    expect(assistant.error.value).toContain('网络中断')
    expect(assistant.messages.value).toEqual([])
    expect(assistant.question.value).toBe('创建工单')
  })

  it('reuses the request id when retrying the same failed message', async () => {
    vi.mocked(runAgent)
      .mockRejectedValueOnce(
        new AgentApiError('网络中断', 0, 'NETWORK_ERROR'),
      )
      .mockResolvedValueOnce(response('ticket_request', 'ticket_draft_ready'))
    vi.mocked(getAgentConversationHistory).mockResolvedValue(
      history(firstConversationId),
    )
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [],
      total: 0,
      limit: 30,
      offset: 0,
    })
    const assistant = useAgentAssistant()
    assistant.question.value = '创建工单'

    await assistant.send()
    await assistant.send()

    const calls = vi.mocked(runAgent).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0][2]).toBe(calls[1][2])
  })

  it('stores only the conversation id, never message content', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.mocked(runAgent).mockResolvedValue(
      response('general_chat', 'completed'),
    )
    vi.mocked(getAgentConversationHistory).mockResolvedValue(
      history(firstConversationId, '敏感问题', '助手回答'),
    )
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [
        conversation(firstConversationId, '敏感问题', '2026-11-15T00:05:00Z'),
      ],
      total: 1,
      limit: 30,
      offset: 0,
    })
    const assistant = useAgentAssistant()
    assistant.question.value = '敏感问题'

    await assistant.send()

    expect([...storage.values.entries()]).toEqual([
      ['opspilot.agent.lastConversationId', firstConversationId],
    ])
    expect(JSON.stringify([...storage.values.entries()])).not.toContain('助手回答')
  })

  it('prevents duplicate submits while one request is active', async () => {
    let resolveRequest: ((value: AgentRunResponse) => void) | undefined
    vi.mocked(runAgent).mockImplementation(
      () => new Promise((resolve) => {
        resolveRequest = resolve
      }),
    )
    vi.mocked(getAgentConversationHistory).mockResolvedValue(
      history(firstConversationId),
    )
    vi.mocked(listAgentConversations).mockResolvedValue({
      items: [],
      total: 0,
      limit: 30,
      offset: 0,
    })
    const assistant = useAgentAssistant()
    assistant.question.value = '你好'

    const first = assistant.run()
    const second = assistant.run()

    expect(runAgent).toHaveBeenCalledTimes(1)
    resolveRequest?.(response('general_chat', 'completed'))
    await Promise.all([first, second])
  })
})
