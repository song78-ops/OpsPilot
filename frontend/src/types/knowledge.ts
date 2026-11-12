export type RetrievalMode = 'dense' | 'bm25' | 'hybrid'
export type RagStatus = 'answered' | 'insufficient_evidence'

export interface DocumentSummary {
  document_id: string
  filename: string
  extension: string
  content_type: string | null
  file_size: number
  content_sha256: string
  uploaded_at: string
  chunk_size: number
  chunk_overlap: number
  chunk_count: number
}

export interface DocumentChunk {
  document_id: string
  chunk_id: string
  filename: string
  page_number: number | null
  chunk_index: number
  content: string
  char_count: number
}

export interface DocumentDetail extends DocumentSummary {
  chunks: DocumentChunk[]
}

export interface DocumentListResponse {
  items: DocumentSummary[]
  total: number
}

export interface DocumentIndexResponse {
  document_id: string
  indexed_chunks: number
  indexed_parts: number
  embedding_model: string
  vector_dimension: number
  index_version: number
  collection_name: string
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
}

export interface RagAskRequest {
  query: string
  top_k?: number | null
  mode: RetrievalMode
  rerank: boolean
  candidate_k?: number | null
  document_id?: string | null
}

export interface RagSource {
  citation_id: number
  document_id: string
  chunk_id: string
  filename: string
  page_number: number | null
  part_index: number
  content_excerpt: string
}

export interface RagLatency {
  retrieval_ms: number
  context_ms: number
  generation_ms: number
  total_ms: number
}

export interface RagAskResponse {
  answer: string | null
  status: RagStatus
  reason: string | null
  sources: RagSource[]
  retrieval_mode: RetrievalMode
  rerank_applied: boolean
  retrieval_count: number
  model: string | null
  usage: TokenUsage | null
  latency_ms: RagLatency
}

export type DocumentIndexState =
  | 'unknown'
  | 'not_indexed'
  | 'indexing'
  | 'indexed'
  | 'error'

