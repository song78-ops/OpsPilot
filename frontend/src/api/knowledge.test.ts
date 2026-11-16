import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  askKnowledgeBase,
  KnowledgeApiError,
  listDocuments,
  uploadDocument,
} from './knowledge'

const documentSummary = {
  document_id: 'a'.repeat(32),
  filename: 'manual.txt',
  extension: '.txt',
  content_type: 'text/plain',
  file_size: 12,
  content_sha256: 'hash',
  uploaded_at: '2026-11-12T00:00:00Z',
  chunk_size: 800,
  chunk_overlap: 120,
  chunk_count: 1,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('knowledge API', () => {
  it('loads the real document list response shape', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ items: [documentSummary], total: 1 }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const response = await listDocuments()

    expect(response.total).toBe(1)
    expect(response.items[0].document_id).toBe('a'.repeat(32))
  })

  it('uploads multipart files without setting a JSON content type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ ...documentSummary, chunks: [] }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['hello'], 'manual.txt', { type: 'text/plain' })

    await uploadDocument(file)

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('file')).toBeInstanceOf(File)
    expect(init.headers).toBeUndefined()
  })

  it('sends the exact RAG request fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          answer: '回答[1]',
          status: 'answered',
          reason: '证据足够',
          sources: [],
          retrieval_mode: 'hybrid',
          rerank_applied: false,
          retrieval_count: 1,
          model: 'deepseek-chat',
          usage: null,
          latency_ms: {
            retrieval_ms: 1,
            context_ms: 1,
            generation_ms: 1,
            total_ms: 3,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await askKnowledgeBase({
      query: '缓存',
      top_k: 5,
      mode: 'hybrid',
      rerank: false,
      candidate_k: null,
      document_id: null,
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/rag/ask')
    expect(JSON.parse(init.body as string)).toEqual({
      query: '缓存',
      top_k: 5,
      mode: 'hybrid',
      rerank: false,
      candidate_k: null,
      document_id: null,
    })
  })

  it('maps backend error codes to Chinese messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'DOCUMENT_NOT_INDEXED',
              message: 'Document is not indexed',
            },
          }),
          { status: 409, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await expect(
      askKnowledgeBase({
        query: '缓存',
        mode: 'hybrid',
        rerank: false,
      }),
    ).rejects.toMatchObject({
      name: 'KnowledgeApiError',
      status: 409,
      code: 'DOCUMENT_NOT_INDEXED',
      message: expect.stringContaining('尚未加入知识库'),
    })
  })
})

