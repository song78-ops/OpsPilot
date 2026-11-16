import { readonly, ref } from 'vue'

import {
  streamChat,
  type ChatStreamEvent,
  type StreamError,
} from '../api/chat'
import type { ChatMessage, TokenUsage } from '../types/chat'

const MAX_MESSAGE_LENGTH = 12_000

const ERROR_MESSAGES: Record<string, string> = {
  CONFIGURATION_ERROR: '服务端尚未配置模型密钥，请联系管理员。',
  LLM_TIMEOUT: '模型响应超时，请稍后重试。',
  LLM_CONNECTION_ERROR: '暂时无法连接模型服务，请检查网络后重试。',
  LLM_UPSTREAM_ERROR: '模型服务返回异常，请稍后重试。',
  STREAM_INTERNAL_ERROR: '生成过程意外中断，请重新发送问题。',
}

function createId(): string {
  return crypto.randomUUID()
}

function friendlyError(event: StreamError): string {
  return ERROR_MESSAGES[event.code] ?? event.message
}

export function useChat() {
  const messages = ref<ChatMessage[]>([])
  const isGenerating = ref(false)
  const usage = ref<TokenUsage | null>(null)
  const activeController = ref<AbortController | null>(null)

  function handleStreamEvent(
    event: ChatStreamEvent,
    assistantMessage: ChatMessage,
  ) {
    switch (event.event) {
      case 'meta':
        break
      case 'token':
        assistantMessage.content += event.data.text
        break
      case 'usage':
        assistantMessage.usage = event.data
        usage.value = event.data
        break
      case 'error':
        assistantMessage.status = 'error'
        assistantMessage.error = friendlyError(event.data)
        break
      case 'done':
        assistantMessage.status = 'complete'
        break
    }
  }

  async function sendMessage(rawMessage: string) {
    const message = rawMessage.trim()
    if (!message || isGenerating.value) {
      return
    }
    if (message.length > MAX_MESSAGE_LENGTH) {
      throw new Error(`问题不能超过 ${MAX_MESSAGE_LENGTH} 个字符。`)
    }

    const userMessage: ChatMessage = {
      id: createId(),
      role: 'user',
      content: message,
      status: 'complete',
    }
    const newAssistantMessage: ChatMessage = {
      id: createId(),
      role: 'assistant',
      content: '',
      status: 'streaming',
    }

    messages.value.push(userMessage, newAssistantMessage)
    const assistantMessage = messages.value[messages.value.length - 1]
    usage.value = null
    isGenerating.value = true
    const controller = new AbortController()
    activeController.value = controller

    try {
      await streamChat({
        message,
        signal: controller.signal,
        onEvent: (event) => handleStreamEvent(event, assistantMessage),
      })
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        assistantMessage.status = 'stopped'
      } else {
        assistantMessage.status = 'error'
        assistantMessage.error =
          error instanceof Error ? error.message : '生成失败，请稍后重试。'
      }
    } finally {
      if (assistantMessage.status === 'streaming') {
        assistantMessage.status = 'complete'
      }
      if (activeController.value === controller) {
        activeController.value = null
        isGenerating.value = false
      }
    }
  }

  function stopGeneration() {
    activeController.value?.abort()
  }

  function clearConversation() {
    if (isGenerating.value) {
      stopGeneration()
    }
    messages.value = []
    usage.value = null
  }

  return {
    messages: readonly(messages),
    isGenerating: readonly(isGenerating),
    usage: readonly(usage),
    sendMessage,
    stopGeneration,
    clearConversation,
    maxMessageLength: MAX_MESSAGE_LENGTH,
  }
}

