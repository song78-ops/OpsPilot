import { computed, readonly, ref } from 'vue'

import {
  AgentApiError,
  getAgentConversationHistory,
  listAgentConversations,
  runAgent,
} from '../api/agent'
import type {
  AgentRunResponse,
  ConversationHistoryResponse,
  ConversationMessage,
  ConversationSummary,
} from '../types/agent'

const LAST_CONVERSATION_KEY = 'opspilot.agent.lastConversationId'

interface PendingAgentRequest {
  message: string
  conversationId: string | null
  requestId: string
}

function createRequestId(): string {
  if (
    typeof globalThis.crypto !== 'undefined'
    && typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID()
  }
  return `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function errorMessage(error: unknown): string {
  if (error instanceof AgentApiError) {
    return error.message
  }
  return error instanceof Error ? error.message : 'Agent 请求失败，请稍后重试。'
}

function readLastConversationId(): string | null {
  if (typeof localStorage === 'undefined') {
    return null
  }
  return localStorage.getItem(LAST_CONVERSATION_KEY)
}

function persistLastConversationId(conversationId: string) {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(LAST_CONVERSATION_KEY, conversationId)
  }
}

function clearLastConversationId() {
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem(LAST_CONVERSATION_KEY)
  }
}

export function useAgentAssistant() {
  const question = ref('')
  const conversations = ref<ConversationSummary[]>([])
  const messages = ref<ConversationMessage[]>([])
  const currentConversationId = ref<string | null>(null)
  const currentConversationTitle = ref('')
  const latestResult = ref<AgentRunResponse | null>(null)
  const isRunning = ref(false)
  const isLoadingConversations = ref(false)
  const isLoadingHistory = ref(false)
  const error = ref('')
  const notice = ref('')
  let pendingRequest: PendingAgentRequest | null = null

  const isBusy = computed(
    () => isRunning.value
      || isLoadingConversations.value
      || isLoadingHistory.value,
  )

  async function fetchConversations(): Promise<ConversationSummary[]> {
    isLoadingConversations.value = true
    try {
      const response = await listAgentConversations(30, 0)
      conversations.value = response.items
      return response.items
    } catch (caught) {
      error.value = errorMessage(caught)
      return []
    } finally {
      isLoadingConversations.value = false
    }
  }

  async function loadHistory(
    conversationId: string,
    clearRuntimeResult: boolean,
  ): Promise<ConversationHistoryResponse | null> {
    isLoadingHistory.value = true
    try {
      const history = await getAgentConversationHistory(conversationId)
      currentConversationId.value = history.conversation_id
      messages.value = history.messages
      currentConversationTitle.value = (
        conversations.value.find(
          (item) => item.conversation_id === conversationId,
        )?.title
        ?? '历史会话'
      )
      if (clearRuntimeResult) {
        latestResult.value = null
      }
      persistLastConversationId(conversationId)
      error.value = ''
      return history
    } catch (caught) {
      error.value = errorMessage(caught)
      if (
        caught instanceof AgentApiError
        && caught.code === 'CONVERSATION_NOT_FOUND'
        && readLastConversationId() === conversationId
      ) {
        clearLastConversationId()
      }
      return null
    } finally {
      isLoadingHistory.value = false
    }
  }

  async function restore(): Promise<void> {
    if (isBusy.value) {
      return
    }
    error.value = ''
    notice.value = ''
    const items = await fetchConversations()
    const savedId = readLastConversationId()
    if (savedId) {
      const restored = await loadHistory(
        savedId,
        true,
      )
      if (restored) {
        return
      }
      clearLastConversationId()
    }

    const firstId = items[0]?.conversation_id ?? null
    if (firstId) {
      await loadHistory(firstId, true)
    } else if (conversations.value.length === 0) {
      currentConversationId.value = null
      currentConversationTitle.value = '新会话'
      messages.value = []
      latestResult.value = null
    }
  }

  async function refresh(): Promise<void> {
    if (isBusy.value) {
      return
    }
    error.value = ''
    const currentId = currentConversationId.value
    await fetchConversations()
    if (currentId) {
      await loadHistory(currentId, false)
    }
  }

  async function selectConversation(conversationId: string): Promise<void> {
    if (isBusy.value) {
      return
    }
    question.value = ''
    pendingRequest = null
    error.value = ''
    notice.value = ''
    const restored = await loadHistory(
      conversationId,
      true,
    )
    if (restored) {
      error.value = ''
    }
  }

  function startNewConversation(): void {
    if (isBusy.value) {
      return
    }
    currentConversationId.value = null
    currentConversationTitle.value = '新会话'
    messages.value = []
    latestResult.value = null
    question.value = ''
    pendingRequest = null
    error.value = ''
    notice.value = '新会话将在首次发送消息时由后端创建。'
    clearLastConversationId()
  }

  async function send(): Promise<AgentRunResponse | null> {
    const message = question.value.trim()
    if (!message || isBusy.value) {
      return null
    }

    const requestedConversationId = currentConversationId.value
    const requestId = (
      pendingRequest
      && pendingRequest.message === message
      && pendingRequest.conversationId === requestedConversationId
    )
      ? pendingRequest.requestId
      : createRequestId()
    pendingRequest = {
      message,
      conversationId: requestedConversationId,
      requestId,
    }
    isRunning.value = true
    error.value = ''
    notice.value = ''
    try {
      const response = await runAgent(
        message,
        requestedConversationId,
        requestId,
      )
      if (!response.conversation_id) {
        throw new Error('后端未返回 conversation_id。')
      }

      pendingRequest = null
      currentConversationId.value = response.conversation_id
      persistLastConversationId(response.conversation_id)
      question.value = ''
      latestResult.value = response

      const history = await loadHistory(
        response.conversation_id,
        false,
      )
      if (!history) {
        error.value = 'Agent 请求已完成，但会话历史刷新失败。'
        return response
      }
      await fetchConversations()
      currentConversationTitle.value = (
        conversations.value.find(
          (item) => item.conversation_id === response.conversation_id,
        )?.title
        ?? '当前会话'
      )
      notice.value = '消息已由服务端持久化。'
      return response
    } catch (caught) {
      error.value = errorMessage(caught)
      return null
    } finally {
      isRunning.value = false
    }
  }

  function clear() {
    if (isRunning.value) {
      return
    }
    latestResult.value = null
    error.value = ''
  }

  return {
    question,
    conversations: readonly(conversations),
    messages: readonly(messages),
    currentConversationId: readonly(currentConversationId),
    currentConversationTitle: readonly(currentConversationTitle),
    latestResult: readonly(latestResult),
    isRunning: readonly(isRunning),
    isLoadingConversations: readonly(isLoadingConversations),
    isLoadingHistory: readonly(isLoadingHistory),
    isBusy,
    error: readonly(error),
    notice: readonly(notice),
    restore,
    refresh,
    selectConversation,
    startNewConversation,
    send,
    run: send,
    clear,
  }
}
