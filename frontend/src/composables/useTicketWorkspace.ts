import { computed, reactive, readonly, ref } from 'vue'

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
  ApprovalDecision,
  ApprovalDetailResponse,
  TicketDraft,
  TicketDraftUpdateRequest,
} from '../types/agent'

const THREAD_STORAGE_KEY = 'opspilot.approval.threads.v1'

function readThreadIds(): Record<string, string> {
  if (typeof localStorage === 'undefined') {
    return {}
  }
  try {
    const value = JSON.parse(localStorage.getItem(THREAD_STORAGE_KEY) ?? '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return {}
    }
    return Object.fromEntries(
      Object.entries(value).filter(
        (entry): entry is [string, string] => typeof entry[1] === 'string',
      ),
    )
  } catch {
    return {}
  }
}

function persistThreadIds(threadIds: Record<string, string>) {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.setItem(THREAD_STORAGE_KEY, JSON.stringify(threadIds))
}

function errorMessage(error: unknown): string {
  if (error instanceof AgentApiError) {
    return error.message
  }
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

export function useTicketWorkspace() {
  const drafts = ref<TicketDraft[]>([])
  const selectedDraft = ref<TicketDraft | null>(null)
  const approval = ref<ApprovalDetailResponse | null>(null)
  const threadIds = reactive<Record<string, string>>(readThreadIds())
  const isLoading = ref(false)
  const isLoadingDetail = ref(false)
  const isSaving = ref(false)
  const isRequestingApproval = ref(false)
  const isDeciding = ref(false)
  const error = ref('')
  const notice = ref('')

  const selectedThreadId = computed(() => {
    const draft = selectedDraft.value
    return draft ? threadIds[draft.id] ?? null : null
  })
  const isBusy = computed(
    () => isLoading.value
      || isLoadingDetail.value
      || isSaving.value
      || isRequestingApproval.value
      || isDeciding.value,
  )
  const canEdit = computed(
    () => selectedDraft.value?.status === 'draft' && !isBusy.value,
  )

  function setThreadId(draftId: string, threadId: string) {
    threadIds[draftId] = threadId
    persistThreadIds(threadIds)
  }

  function removeThreadId(draftId: string) {
    delete threadIds[draftId]
    persistThreadIds(threadIds)
  }

  function applyApproval(response: ApprovalDetailResponse) {
    approval.value = response
    setThreadId(response.draft.id, response.approval.thread_id)
    selectedDraft.value = response.draft
  }

  async function refreshDrafts() {
    if (isLoading.value) {
      return
    }
    isLoading.value = true
    error.value = ''
    try {
      const response = await listTicketDrafts()
      drafts.value = response.items
      const current = selectedDraft.value
      if (current) {
        const refreshed = response.items.find((draft) => draft.id === current.id)
        selectedDraft.value = refreshed ?? null
        if (!refreshed) {
          approval.value = null
        }
      }
    } catch (caught) {
      error.value = errorMessage(caught)
    } finally {
      isLoading.value = false
    }
  }

  async function selectDraft(draftId: string) {
    if (isBusy.value && selectedDraft.value?.id !== draftId) {
      return
    }
    isLoadingDetail.value = true
    error.value = ''
    approval.value = null
    try {
      const draft = await getTicketDraft(draftId)
      selectedDraft.value = draft
      const threadId = threadIds[draftId]
      if (threadId && draft.status !== 'draft') {
        const response = await getTicketApproval(threadId)
        applyApproval(response)
      }
    } catch (caught) {
      if (
        caught instanceof AgentApiError
        && caught.code === 'TICKET_APPROVAL_NOT_FOUND'
      ) {
        removeThreadId(draftId)
        approval.value = null
      }
      error.value = errorMessage(caught)
    } finally {
      isLoadingDetail.value = false
    }
  }

  async function focusAgentDraft(draft: TicketDraft) {
    await refreshDrafts()
    await selectDraft(draft.id)
    notice.value = `已同步 Agent 返回的草稿“${draft.title}”。`
  }

  async function updateSelected(payload: TicketDraftUpdateRequest) {
    const draft = selectedDraft.value
    if (!draft || draft.status !== 'draft' || isBusy.value) {
      return null
    }
    isSaving.value = true
    error.value = ''
    notice.value = ''
    try {
      await updateTicketDraft(draft.id, payload)
      const refreshed = await getTicketDraft(draft.id)
      selectedDraft.value = refreshed
      await refreshDrafts()
      notice.value = '草稿修改已由后端确认。'
      return refreshed
    } catch (caught) {
      error.value = errorMessage(caught)
      return null
    } finally {
      isSaving.value = false
    }
  }

  async function submitSelectedForApproval() {
    const draft = selectedDraft.value
    if (!draft || draft.status !== 'draft' || isBusy.value) {
      return null
    }
    isRequestingApproval.value = true
    error.value = ''
    notice.value = ''
    try {
      const response = await requestTicketApproval(draft.id)
      applyApproval(response)
      await refreshDrafts()
      notice.value = '审批流程已创建，LangGraph 正在等待人工决定。'
      return response
    } catch (caught) {
      error.value = errorMessage(caught)
      return null
    } finally {
      isRequestingApproval.value = false
    }
  }

  async function refreshSelectedApproval() {
    const threadId = selectedThreadId.value
    if (!threadId || isBusy.value) {
      return null
    }
    isLoadingDetail.value = true
    error.value = ''
    try {
      const response = await getTicketApproval(threadId)
      applyApproval(response)
      await refreshDrafts()
      return response
    } catch (caught) {
      error.value = errorMessage(caught)
      return null
    } finally {
      isLoadingDetail.value = false
    }
  }

  async function decideSelected(
    decision: ApprovalDecision,
    note?: string | null,
  ) {
    const draft = selectedDraft.value
    const threadId = selectedThreadId.value
    if (
      !draft
      || !threadId
      || draft.status !== 'pending_approval'
      || approval.value?.waiting_for_decision !== true
      || isBusy.value
    ) {
      return null
    }

    isDeciding.value = true
    error.value = ''
    notice.value = ''
    try {
      const decisionResponse = await decideTicketApproval(threadId, {
        decision,
        note: note?.trim() || null,
      })
      const [refreshedApproval, refreshedDraft] = await Promise.all([
        getTicketApproval(threadId),
        getTicketDraft(draft.id),
      ])
      const expectedStatus = decision === 'approve' ? 'approved' : 'rejected'
      if (
        refreshedApproval.approval.status !== expectedStatus
        || refreshedDraft.status !== expectedStatus
        || decisionResponse.draft.status !== expectedStatus
      ) {
        throw new Error('审批接口返回成功，但重新查询到的状态不一致。')
      }
      applyApproval(refreshedApproval)
      selectedDraft.value = refreshedDraft
      await refreshDrafts()
      notice.value = decision === 'approve'
        ? '审批已批准，后端状态和审批流程均已重新确认。'
        : '审批已拒绝，后端状态和审批流程均已重新确认。'
      return refreshedApproval
    } catch (caught) {
      error.value = errorMessage(caught)
      return null
    } finally {
      isDeciding.value = false
    }
  }

  function clearMessages() {
    error.value = ''
    notice.value = ''
  }

  return {
    drafts: readonly(drafts),
    selectedDraft: readonly(selectedDraft),
    approval: readonly(approval),
    threadIds: readonly(threadIds),
    selectedThreadId,
    isBusy,
    canEdit,
    isLoading: readonly(isLoading),
    isLoadingDetail: readonly(isLoadingDetail),
    isSaving: readonly(isSaving),
    isRequestingApproval: readonly(isRequestingApproval),
    isDeciding: readonly(isDeciding),
    error: readonly(error),
    notice: readonly(notice),
    refreshDrafts,
    selectDraft,
    focusAgentDraft,
    updateSelected,
    submitSelectedForApproval,
    refreshSelectedApproval,
    decideSelected,
    clearMessages,
  }
}
