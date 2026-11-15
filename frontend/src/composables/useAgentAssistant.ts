import { readonly, ref } from 'vue'

import { AgentApiError, runAgent } from '../api/agent'
import type { AgentRunResponse } from '../types/agent'

function errorMessage(error: unknown): string {
  if (error instanceof AgentApiError) {
    return error.message
  }
  return error instanceof Error ? error.message : 'Agent 请求失败，请稍后重试。'
}

export function useAgentAssistant() {
  const question = ref('')
  const isRunning = ref(false)
  const error = ref('')
  const result = ref<AgentRunResponse | null>(null)

  async function run(): Promise<AgentRunResponse | null> {
    const message = question.value.trim()
    if (!message || isRunning.value) {
      return null
    }

    isRunning.value = true
    error.value = ''
    try {
      const response = await runAgent(message)
      result.value = response
      question.value = ''
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
    result.value = null
    error.value = ''
  }

  return {
    question,
    isRunning: readonly(isRunning),
    error: readonly(error),
    result: readonly(result),
    run,
    clear,
  }
}
