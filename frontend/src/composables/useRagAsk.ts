import { readonly, ref } from 'vue'

import {
  askKnowledgeBase,
  KnowledgeApiError,
} from '../api/knowledge'
import type {
  RagAskResponse,
  RetrievalMode,
} from '../types/knowledge'

export interface RagAskEntry {
  id: string
  question: string
  response: RagAskResponse
  askedAt: string
}

function errorMessage(error: unknown): string {
  if (error instanceof KnowledgeApiError) {
    return error.message
  }
  return error instanceof Error ? error.message : '知识库问答失败，请稍后重试。'
}

export function useRagAsk() {
  const question = ref('')
  const mode = ref<RetrievalMode>('hybrid')
  const rerank = ref(false)
  const topK = ref(5)
  const candidateK = ref(20)
  const documentId = ref<string | null>(null)
  const isAsking = ref(false)
  const error = ref('')
  const entries = ref<RagAskEntry[]>([])

  async function ask() {
    const query = question.value.trim()
    if (!query || isAsking.value) {
      return
    }
    if (!Number.isInteger(topK.value) || topK.value < 1 || topK.value > 20) {
      error.value = 'Top-K 必须是 1 到 20 之间的整数。'
      return
    }
    if (
      rerank.value
      && (
        !Number.isInteger(candidateK.value)
        || candidateK.value < topK.value
        || candidateK.value > 20
      )
    ) {
      error.value = '精排候选数必须不少于 Top-K，并且不超过 20。'
      return
    }

    isAsking.value = true
    error.value = ''
    try {
      const response = await askKnowledgeBase({
        query,
        top_k: topK.value,
        mode: mode.value,
        rerank: rerank.value,
        candidate_k: rerank.value ? candidateK.value : null,
        document_id: documentId.value || null,
      })
      entries.value.push({
        id: crypto.randomUUID(),
        question: query,
        response,
        askedAt: new Date().toISOString(),
      })
      question.value = ''
    } catch (caught) {
      error.value = errorMessage(caught)
    } finally {
      isAsking.value = false
    }
  }

  function clearHistory() {
    if (isAsking.value) {
      return
    }
    entries.value = []
    error.value = ''
  }

  return {
    question,
    mode,
    rerank,
    topK,
    candidateK,
    documentId,
    isAsking: readonly(isAsking),
    error: readonly(error),
    entries: readonly(entries),
    ask,
    clearHistory,
  }
}

