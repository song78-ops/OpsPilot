import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  AgentApiError,
  decideTicketApproval,
  getTicketApproval,
  getTicketDraft,
  listTicketDrafts,
  requestTicketApproval,
  updateTicketDraft,
} from '../api/agent'
import type {
  ApprovalDecisionResponse,
  ApprovalDetailResponse,
  TicketDraft,
} from '../types/agent'
import { useTicketWorkspace } from './useTicketWorkspace'

vi.mock('../api/agent', () => ({
  listTicketDrafts: vi.fn(),
  getTicketDraft: vi.fn(),
  updateTicketDraft: vi.fn(),
  requestTicketApproval: vi.fn(),
  getTicketApproval: vi.fn(),
  decideTicketApproval: vi.fn(),
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

const pendingDraft: TicketDraft = {
  ...draft,
  status: 'pending_approval',
}

const approvalDetail: ApprovalDetailResponse = {
  approval: {
    thread_id: 'b'.repeat(32),
    draft_id: draft.id,
    draft_version: 1,
    status: 'pending_approval',
    note: null,
    requested_at: '2026-11-15T00:00:00Z',
    decided_at: null,
  },
  draft: pendingDraft,
  waiting_for_decision: true,
  checkpoint_next: ['await_decision'],
}

function decisionResponse(
  decision: 'approve' | 'reject',
): ApprovalDecisionResponse {
  const status = decision === 'approve' ? 'approved' : 'rejected'
  return {
    approval: {
      ...approvalDetail.approval,
      status,
      decided_at: '2026-11-15T01:00:00Z',
    },
    draft: { ...pendingDraft, status },
    decision,
    executed_nodes: ['load_draft', 'await_decision', 'apply_decision'],
    waiting_for_decision: false,
  }
}

function finalApproval(
  decision: 'approve' | 'reject',
): ApprovalDetailResponse {
  const status = decision === 'approve' ? 'approved' : 'rejected'
  return {
    approval: {
      ...approvalDetail.approval,
      status,
      decided_at: '2026-11-15T01:00:00Z',
    },
    draft: { ...pendingDraft, status },
    waiting_for_decision: false,
    checkpoint_next: [],
  }
}

async function preparePendingWorkspace() {
  vi.mocked(listTicketDrafts)
    .mockResolvedValueOnce({ items: [draft], total: 1 })
    .mockResolvedValueOnce({ items: [pendingDraft], total: 1 })
  vi.mocked(getTicketDraft).mockResolvedValueOnce(draft)
  vi.mocked(requestTicketApproval).mockResolvedValue(approvalDetail)
  const workspace = useTicketWorkspace()
  await workspace.refreshDrafts()
  await workspace.selectDraft(draft.id)
  await workspace.submitSelectedForApproval()
  return workspace
}

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('useTicketWorkspace', () => {
  it('loads a real draft list and selected detail', async () => {
    vi.mocked(listTicketDrafts).mockResolvedValue({ items: [draft], total: 1 })
    vi.mocked(getTicketDraft).mockResolvedValue(draft)
    const workspace = useTicketWorkspace()

    await workspace.refreshDrafts()
    await workspace.selectDraft(draft.id)

    expect(workspace.drafts.value[0].id).toBe(draft.id)
    expect(workspace.selectedDraft.value?.title).toBe(draft.title)
    expect(workspace.canEdit.value).toBe(true)
  })

  it('updates a draft then re-reads the persisted version', async () => {
    const updated = {
      ...draft,
      description: '已确认网线正常。',
      version: 2,
      updated_at: '2026-11-15T01:00:00Z',
    }
    vi.mocked(listTicketDrafts)
      .mockResolvedValueOnce({ items: [draft], total: 1 })
      .mockResolvedValueOnce({ items: [updated], total: 1 })
    vi.mocked(getTicketDraft)
      .mockResolvedValueOnce(draft)
      .mockResolvedValueOnce(updated)
    vi.mocked(updateTicketDraft).mockResolvedValue(updated)
    const workspace = useTicketWorkspace()
    await workspace.refreshDrafts()
    await workspace.selectDraft(draft.id)

    const result = await workspace.updateSelected({
      description: '已确认网线正常。',
    })

    expect(result?.version).toBe(2)
    expect(workspace.selectedDraft.value?.description).toContain('网线正常')
    expect(updateTicketDraft).toHaveBeenCalledWith(draft.id, {
      description: '已确认网线正常。',
    })
    expect(getTicketDraft).toHaveBeenCalledTimes(2)
  })

  it('requests approval and stores the returned thread id in local state', async () => {
    const workspace = await preparePendingWorkspace()

    expect(requestTicketApproval).toHaveBeenCalledWith(draft.id)
    expect(workspace.selectedDraft.value?.status).toBe('pending_approval')
    expect(workspace.selectedThreadId.value).toBe(approvalDetail.approval.thread_id)
    expect(workspace.approval.value?.waiting_for_decision).toBe(true)
  })

  it.each(['approve', 'reject'] as const)(
    'refreshes both approval and draft state after %s',
    async (decision) => {
      const workspace = await preparePendingWorkspace()
      vi.mocked(getTicketApproval).mockResolvedValue(
        finalApproval(decision),
      )
      vi.mocked(getTicketDraft).mockResolvedValue(
        finalApproval(decision).draft,
      )
      vi.mocked(listTicketDrafts).mockResolvedValue({
        items: [finalApproval(decision).draft],
        total: 1,
      })
      vi.mocked(decideTicketApproval).mockResolvedValue(
        decisionResponse(decision),
      )

      const result = await workspace.decideSelected(decision, '测试备注')

      const expected = decision === 'approve' ? 'approved' : 'rejected'
      expect(result?.draft.status).toBe(expected)
      expect(workspace.selectedDraft.value?.status).toBe(expected)
      expect(workspace.notice.value).toContain('重新确认')
      expect(getTicketApproval).toHaveBeenCalled()
      expect(getTicketDraft).toHaveBeenCalled()
    },
  )

  it('keeps a 409 conflict visible and does not change local status', async () => {
    const workspace = await preparePendingWorkspace()
    vi.mocked(decideTicketApproval).mockRejectedValue(
      new AgentApiError(
        '该审批已经处理，不能重复批准或拒绝。',
        409,
        'TICKET_APPROVAL_STATE_CONFLICT',
      ),
    )

    const result = await workspace.decideSelected('approve')

    expect(result).toBeNull()
    expect(workspace.error.value).toContain('不能重复批准或拒绝')
    expect(workspace.selectedDraft.value?.status).toBe('pending_approval')
  })

  it('clears a stale local thread id when the backend approval is missing', async () => {
    const storage = new Map<string, string>()
    storage.set(
      'opspilot.approval.threads.v1',
      JSON.stringify({ [draft.id]: approvalDetail.approval.thread_id }),
    )
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    })
    vi.mocked(listTicketDrafts).mockResolvedValue({
      items: [pendingDraft],
      total: 1,
    })
    vi.mocked(getTicketDraft).mockResolvedValue(pendingDraft)
    vi.mocked(getTicketApproval).mockRejectedValue(
      new AgentApiError(
        '审批流程不存在，或本地记录的流程 ID 已失效。',
        404,
        'TICKET_APPROVAL_NOT_FOUND',
      ),
    )
    const workspace = useTicketWorkspace()
    await workspace.refreshDrafts()

    await workspace.selectDraft(draft.id)

    expect(workspace.selectedThreadId.value).toBeNull()
    expect(workspace.approval.value).toBeNull()
    expect(workspace.error.value).toContain('流程 ID 已失效')
  })

  it('rejects a decision when refresh returns an inconsistent status', async () => {
    const workspace = await preparePendingWorkspace()
    vi.mocked(decideTicketApproval).mockResolvedValue(
      decisionResponse('approve'),
    )
    vi.mocked(getTicketApproval).mockResolvedValue(approvalDetail)
    vi.mocked(getTicketDraft).mockResolvedValue(pendingDraft)

    const result = await workspace.decideSelected('approve')

    expect(result).toBeNull()
    expect(workspace.error.value).toContain('状态不一致')
    expect(workspace.notice.value).toBe('')
  })

  it('prevents duplicate decision requests while one is active', async () => {
    const workspace = await preparePendingWorkspace()
    let resolveDecision: ((value: ApprovalDecisionResponse) => void) | undefined
    vi.mocked(decideTicketApproval).mockImplementation(
      () => new Promise((resolve) => {
        resolveDecision = resolve
      }),
    )
    vi.mocked(getTicketApproval).mockResolvedValue(finalApproval('approve'))
    vi.mocked(getTicketDraft).mockResolvedValue(finalApproval('approve').draft)
    vi.mocked(listTicketDrafts).mockResolvedValue({
      items: [finalApproval('approve').draft],
      total: 1,
    })

    const first = workspace.decideSelected('approve')
    const second = workspace.decideSelected('approve')

    expect(decideTicketApproval).toHaveBeenCalledTimes(1)
    resolveDecision?.(decisionResponse('approve'))
    await Promise.all([first, second])
  })
})
