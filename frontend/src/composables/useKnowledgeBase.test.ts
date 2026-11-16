import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  indexDocument,
  listDocuments,
  uploadDocument,
} from '../api/knowledge'
import { useKnowledgeBase } from './useKnowledgeBase'

vi.mock('../api/knowledge', () => ({
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  indexDocument: vi.fn(),
  KnowledgeApiError: class extends Error {},
}))

const summary = {
  document_id: 'a'.repeat(32),
  filename: 'manual.txt',
  extension: '.txt',
  content_type: 'text/plain',
  file_size: 100,
  content_sha256: 'hash',
  uploaded_at: '2026-11-12T00:00:00Z',
  chunk_size: 800,
  chunk_overlap: 120,
  chunk_count: 2,
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('useKnowledgeBase', () => {
  it('marks a successful upload as not indexed in this session', async () => {
    vi.mocked(listDocuments).mockResolvedValue({ items: [summary], total: 1 })
    vi.mocked(uploadDocument).mockResolvedValue({ ...summary, chunks: [] })
    const knowledge = useKnowledgeBase()

    const result = await knowledge.upload(
      new File(['content'], 'manual.txt', { type: 'text/plain' }),
    )

    expect(result?.document_id).toBe(summary.document_id)
    expect(knowledge.documents.value).toHaveLength(1)
    expect(knowledge.indexStates[summary.document_id]).toBe('not_indexed')
    expect(knowledge.notice.value).toContain('可加入知识库')
  })

  it('only claims indexed after an index API success', async () => {
    vi.mocked(indexDocument).mockResolvedValue({
      document_id: summary.document_id,
      indexed_chunks: 2,
      indexed_parts: 2,
      embedding_model: 'BGE',
      vector_dimension: 512,
      index_version: 1,
      collection_name: 'collection',
    })
    const knowledge = useKnowledgeBase()

    await knowledge.indexDocuments([summary.document_id])

    expect(indexDocument).toHaveBeenCalledWith(summary.document_id)
    expect(knowledge.indexStates[summary.document_id]).toBe('indexed')
    expect(knowledge.notice.value).toContain('现在可以查找')
  })

  it('rejects unsupported and oversized files before network access', async () => {
    const knowledge = useKnowledgeBase()

    await knowledge.upload(new File(['data'], 'image.png'))
    expect(knowledge.error.value).toContain('请选择 PDF')

    await knowledge.upload(
      new File([new ArrayBuffer(11 * 1024 * 1024)], 'large.txt'),
    )
    expect(knowledge.error.value).toContain('10 MiB')
    expect(uploadDocument).not.toHaveBeenCalled()
  })

  it('keeps an explicit per-document indexing failure', async () => {
    vi.mocked(indexDocument).mockRejectedValue(
      new Error('索引服务暂时不可用'),
    )
    const knowledge = useKnowledgeBase()

    await knowledge.indexDocuments([summary.document_id])

    expect(knowledge.indexStates[summary.document_id]).toBe('error')
    expect(knowledge.error.value).toContain('索引服务暂时不可用')
  })
})

