import { computed, readonly, reactive, ref } from 'vue'

import {
  indexDocument,
  KnowledgeApiError,
  listDocuments,
  uploadDocument,
} from '../api/knowledge'
import type {
  DocumentIndexResponse,
  DocumentIndexState,
  DocumentSummary,
} from '../types/knowledge'

const MAX_FILE_BYTES = 10 * 1024 * 1024
const SUPPORTED_EXTENSIONS = new Set(['pdf', 'docx', 'txt', 'md', 'markdown'])

function fileExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

function errorMessage(error: unknown): string {
  if (error instanceof KnowledgeApiError) {
    return error.message
  }
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

export function useKnowledgeBase() {
  const documents = ref<DocumentSummary[]>([])
  const indexStates = reactive<Record<string, DocumentIndexState>>({})
  const selectedIds = ref<string[]>([])
  const isLoading = ref(false)
  const isUploading = ref(false)
  const isIndexing = ref(false)
  const error = ref('')
  const notice = ref('')
  const lastIndexResults = ref<DocumentIndexResponse[]>([])

  const selectedCount = computed(() => selectedIds.value.length)

  async function refresh() {
    if (isLoading.value) {
      return
    }
    isLoading.value = true
    error.value = ''
    try {
      const response = await listDocuments()
      documents.value = response.items
      const availableIds = new Set(response.items.map((item) => item.document_id))
      for (const document of response.items) {
        if (!indexStates[document.document_id]) {
          indexStates[document.document_id] = 'unknown'
        }
      }
      for (const id of Object.keys(indexStates)) {
        if (!availableIds.has(id)) {
          delete indexStates[id]
        }
      }
      selectedIds.value = selectedIds.value.filter((id) => availableIds.has(id))
    } catch (caught) {
      error.value = errorMessage(caught)
    } finally {
      isLoading.value = false
    }
  }

  async function upload(file: File) {
    if (isUploading.value) {
      return null
    }
    error.value = ''
    notice.value = ''
    const extension = fileExtension(file.name)
    if (!SUPPORTED_EXTENSIONS.has(extension)) {
      error.value = '请选择 PDF、DOCX、TXT、.md 或 .markdown 文件。'
      return null
    }
    if (file.size > MAX_FILE_BYTES) {
      error.value = '前端限制单文件不超过 10 MiB，请压缩或拆分文件。'
      return null
    }

    isUploading.value = true
    try {
      const detail = await uploadDocument(file)
      await refresh()
      indexStates[detail.document_id] = 'not_indexed'
      notice.value = `“${detail.filename}”上传成功，可加入知识库后查询。`
      return detail
    } catch (caught) {
      error.value = errorMessage(caught)
      return null
    } finally {
      isUploading.value = false
    }
  }

  function toggleSelection(documentId: string) {
    if (selectedIds.value.includes(documentId)) {
      selectedIds.value = selectedIds.value.filter((id) => id !== documentId)
    } else {
      selectedIds.value = [...selectedIds.value, documentId]
    }
  }

  async function indexDocuments(documentIds: string[]) {
    if (isIndexing.value) {
      return []
    }
    const uniqueIds = [...new Set(documentIds)].filter(Boolean)
    if (uniqueIds.length === 0) {
      error.value = '请先选择需要加入知识库的文档。'
      return []
    }

    isIndexing.value = true
    error.value = ''
    notice.value = ''
    const results: DocumentIndexResponse[] = []
    const failures: string[] = []

    for (const documentId of uniqueIds) {
      indexStates[documentId] = 'indexing'
      try {
        const result = await indexDocument(documentId)
        results.push(result)
        indexStates[documentId] = 'indexed'
        notice.value = `已收录 ${result.indexed_parts} 个内容片段，现在可以查找。`
      } catch (caught) {
        indexStates[documentId] = 'error'
        failures.push(errorMessage(caught))
      }
    }

    lastIndexResults.value = results
    if (failures.length > 0) {
      error.value = failures.join('；')
    }
    selectedIds.value = []
    isIndexing.value = false
    return results
  }

  function clearMessages() {
    error.value = ''
    notice.value = ''
  }

  return {
    documents: readonly(documents),
    indexStates: readonly(indexStates),
    selectedIds: readonly(selectedIds),
    selectedCount,
    isLoading: readonly(isLoading),
    isUploading: readonly(isUploading),
    isIndexing: readonly(isIndexing),
    error: readonly(error),
    notice: readonly(notice),
    lastIndexResults: readonly(lastIndexResults),
    refresh,
    upload,
    toggleSelection,
    indexDocuments,
    clearMessages,
    maxFileBytes: MAX_FILE_BYTES,
  }
}

