import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  askKnowledgeBase,
  KnowledgeApiError,
} from '../api/knowledge'
import type { RagAskResponse } from '../types/knowledge'
import { useRagAsk } from './useRagAsk'

vi.mock('../api/knowledge', () => ({
  askKnowledgeBase: vi.fn(),
  KnowledgeApiError: class extends Error {
    constructor(
      message: string,
      readonly status = 0,
      readonly code = 'ERROR',
    ) {
      super(message)
      this.name = 'KnowledgeApiError'
    }
  },
}))

const answered: RagAskResponse = {
  answer: 'Redis 使用互斥锁[1]。',
  status: 'answered',
  reason: '证据支持',
  sources: [
    {
      citation_id: 1,
      document_id: 'a'.repeat(32),
      chunk_id: `${'a'.repeat(32)}:0001`,
      filename: 'redis.txt',
      page_number: null,
      part_index: 1,
      content_excerpt: 'Redis 使用互斥锁。',
    },
  ],
  retrieval_mode: 'hybrid',
  rerank_applied: false,
  retrieval_count: 1,
  model: 'deepseek-chat',
  usage: { prompt_tokens: 10, completion_tokens: 5 },
  latency_ms: {
    retrieval_ms: 1,
    context_ms: 1,
    generation_ms: 10,
    total_ms: 12,
  },
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('useRagAsk', () => {
  it('uses hybrid and rerank=false defaults', async () => {
    vi.mocked(askKnowledgeBase).mockResolvedValue(answered)
    const rag = useRagAsk()
    rag.question.value = '缓存击穿怎么办？'

    await rag.ask()

    expect(askKnowledgeBase).toHaveBeenCalledWith({
      query: '缓存击穿怎么办？',
      top_k: 5,
      mode: 'hybrid',
      rerank: false,
      candidate_k: null,
      document_id: null,
    })
    expect(rag.entries.value[0].response.status).toBe('answered')
    expect(rag.question.value).toBe('')
  })

  it('keeps insufficient_evidence as a valid non-error result', async () => {
    vi.mocked(askKnowledgeBase).mockResolvedValue({
      ...answered,
      answer: null,
      status: 'insufficient_evidence',
      reason: '知识库没有足够证据。',
      sources: [],
      usage: null,
    })
    const rag = useRagAsk()
    rag.question.value = '年假余额是多少？'

    await rag.ask()

    expect(rag.error.value).toBe('')
    expect(rag.entries.value[0].response.status).toBe(
      'insufficient_evidence',
    )
  })

  it('shows a Chinese API error and does not add a result', async () => {
    vi.mocked(askKnowledgeBase).mockRejectedValue(
      new KnowledgeApiError('模型响应超时，请稍后重试。', 504, 'LLM_TIMEOUT'),
    )
    const rag = useRagAsk()
    rag.question.value = '测试错误'

    await rag.ask()

    expect(rag.error.value).toContain('模型响应超时')
    expect(rag.entries.value).toHaveLength(0)
  })

  it('prevents duplicate submits while a request is active', async () => {
    let resolveRequest: ((value: RagAskResponse) => void) | undefined
    vi.mocked(askKnowledgeBase).mockImplementation(
      () => new Promise((resolve) => {
        resolveRequest = resolve
      }),
    )
    const rag = useRagAsk()
    rag.question.value = '重复提交测试'

    const first = rag.ask()
    const second = rag.ask()

    expect(askKnowledgeBase).toHaveBeenCalledTimes(1)
    resolveRequest?.(answered)
    await Promise.all([first, second])
  })

  it('validates reranker candidate budget before request', async () => {
    const rag = useRagAsk()
    rag.question.value = '缓存'
    rag.rerank.value = true
    rag.topK.value = 10
    rag.candidateK.value = 5

    await rag.ask()

    expect(rag.error.value).toContain('精排候选数')
    expect(askKnowledgeBase).not.toHaveBeenCalled()
  })
})

