import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  AgentApiError,
  decideTicketApproval,
  getAgentConversationHistory,
  getTicketApproval,
  getTicketApprovalByDraft,
  getTicketDraft,
  listTicketDrafts,
  listAgentConversations,
  requestTicketApproval,
  runAgent,
  updateTicketDraft,
} from './agent'

const draft = {
  id: 'a'.repeat(32),
  title: '电脑无法联网',
  description: '办公电脑无法连接公司网络。',
  device_or_system: 'Windows 笔记本',
  status: 'draft',
  version: 1,
  created_at: '2026-11-15T00:00:00Z',
  updated_at: '2026-11-15T00:00:00Z',
}

const approval = {
  approval: {
    thread_id: 'b'.repeat(32),
    draft_id: draft.id,
    draft_version: 1,
    status: 'pending_approval',
    note: null,
    requested_at: '2026-11-15T00:00:00Z',
    decided_at: null,
  },
  draft: { ...draft, status: 'pending_approval' },
  waiting_for_decision: true,
  checkpoint_next: ['await_decision'],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('agent API', () => {
  it('sends the exact Agent request fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        intent: 'general_chat',
        status: 'completed',
        answer: '你好',
        ticket_draft: null,
        sources: [],
        executed_nodes: ['supervisor', 'chat'],
        supervisor_reason: '普通聊天',
        model: 'deepseek-chat',
        usage: null,
        error: null,
        latency_ms: 12,
        node_traces: [],
        tool_calls: [],
        conversation_id: null,
        memory_persisted: false,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await runAgent('你好', null, 'retry-key-1')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/agent/run')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      message: '你好',
      conversation_id: null,
      request_id: 'retry-key-1',
    })
  })

  it('uses the real ticket query and update endpoints', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ items: [draft], total: 1 }))
      .mockResolvedValueOnce(jsonResponse(draft))
      .mockResolvedValueOnce(
        jsonResponse({ ...draft, description: '已更新', version: 2 }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await listTicketDrafts()
    await getTicketDraft(draft.id)
    await updateTicketDraft(draft.id, { description: '已更新' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/tickets/drafts')
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/v1/tickets/drafts/${draft.id}`,
    )
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/api/v1/tickets/drafts/${draft.id}`,
    )
    expect(fetchMock.mock.calls[2][1].method).toBe('PATCH')
    expect(JSON.parse(fetchMock.mock.calls[2][1].body as string)).toEqual({
      description: '已更新',
    })
  })

  it('uses the persisted approval request, query, and decision endpoints', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(approval, 202))
      .mockResolvedValueOnce(jsonResponse(approval))
      .mockResolvedValueOnce(
        jsonResponse({
          approval: {
            ...approval.approval,
            status: 'approved',
            note: '通过',
            decided_at: '2026-11-15T01:00:00Z',
          },
          draft: {
            ...approval.draft,
            status: 'approved',
          },
          decision: 'approve',
          executed_nodes: ['load_draft', 'await_decision', 'apply_decision'],
          waiting_for_decision: false,
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await requestTicketApproval(draft.id)
    await getTicketApproval(approval.approval.thread_id)
    await decideTicketApproval(approval.approval.thread_id, {
      decision: 'approve',
      note: '通过',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/v1/tickets/drafts/${draft.id}/request-approval`,
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/v1/agent/approvals/${approval.approval.thread_id}`,
    )
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/api/v1/agent/approvals/${approval.approval.thread_id}/decision`,
    )
    expect(JSON.parse(fetchMock.mock.calls[2][1].body as string)).toEqual({
      decision: 'approve',
      note: '通过',
    })
  })

  it('looks up an approval by draft id without a local thread id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        draft: approval.draft,
        approval: approval.approval,
        status: 'pending_approval',
        waiting_for_decision: true,
        checkpoint_next: ['await_decision'],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const response = await getTicketApprovalByDraft(draft.id)

    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/v1/tickets/drafts/${draft.id}/approval`,
    )
    expect(response.approval?.thread_id).toBe(approval.approval.thread_id)
    expect(response.waiting_for_decision).toBe(true)
  })

  it('loads paginated conversations and one real history response', async () => {
    const conversationId = 'c'.repeat(32)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              conversation_id: conversationId,
              title: '电脑无法联网',
              created_at: '2026-11-15T00:00:00Z',
              updated_at: '2026-11-15T01:00:00Z',
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          conversation_id: conversationId,
          created_at: '2026-11-15T00:00:00Z',
          updated_at: '2026-11-15T01:00:00Z',
          last_ticket_draft_id: draft.id,
          ticket_references: [draft.id],
          total: 2,
          messages: [
            {
              id: 1,
              role: 'user',
              content: '你好',
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
              content: '你好，我是 OpsPilot。',
              intent: 'general_chat',
              status: 'completed',
              tool_name: null,
              tool_status: null,
              business_reference_id: null,
              created_at: '2026-11-15T00:01:00Z',
            },
          ],
          memory_persisted: true,
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const list = await listAgentConversations()
    const history = await getAgentConversationHistory(conversationId)

    expect(fetchMock.mock.calls[0][0]).toContain('limit=30')
    expect(fetchMock.mock.calls[0][0]).toContain('offset=0')
    expect(fetchMock.mock.calls[1][0]).toContain(
      `/api/v1/agent/conversations/${conversationId}`,
    )
    expect(list.items[0].title).toBe('电脑无法联网')
    expect(history.messages[1].content).toContain('OpsPilot')
  })

  it('maps 409 approval conflicts to a clear Chinese message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: 'TICKET_APPROVAL_STATE_CONFLICT',
              message: 'Approval is no longer waiting',
            },
          },
          409,
        ),
      ),
    )

    await expect(
      decideTicketApproval(approval.approval.thread_id, {
        decision: 'reject',
      }),
    ).rejects.toMatchObject({
      name: 'AgentApiError',
      status: 409,
      code: 'TICKET_APPROVAL_STATE_CONFLICT',
      message: expect.stringContaining('不能重复批准或拒绝'),
    })
  })

  it('reports network failures as AgentApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))

    await expect(runAgent('测试')).rejects.toBeInstanceOf(AgentApiError)
  })
})
