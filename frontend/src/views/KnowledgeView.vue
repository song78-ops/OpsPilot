<script setup lang="ts">
import { onMounted } from 'vue'

import DocumentLibraryPanel from '../components/knowledge/DocumentLibraryPanel.vue'
import RagAskPanel from '../components/knowledge/RagAskPanel.vue'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'

const {
  documents,
  indexStates,
  selectedIds,
  selectedCount,
  isLoading,
  isUploading,
  isIndexing,
  error,
  notice,
  refresh,
  upload,
  toggleSelection,
  indexDocuments,
  clearMessages,
  maxFileBytes,
} = useKnowledgeBase()

onMounted(() => {
  void refresh()
})
</script>

<template>
  <main class="knowledge-page">
    <header class="knowledge-header">
      <div>
        <h1>企业知识库</h1>
        <p class="knowledge-subtitle">
          上传公司资料，快速查找答案并查看引用来源。
        </p>
      </div>
    </header>

    <div class="knowledge-grid">
      <DocumentLibraryPanel
        :documents="documents"
        :index-states="indexStates"
        :selected-ids="selectedIds"
        :selected-count="selectedCount"
        :is-loading="isLoading"
        :is-uploading="isUploading"
        :is-indexing="isIndexing"
        :error="error"
        :notice="notice"
        :max-file-bytes="maxFileBytes"
        :refresh="refresh"
        :upload-file="upload"
        :toggle-selection="toggleSelection"
        :index-selected="() => indexDocuments([...selectedIds])"
        @clear-messages="clearMessages"
      />
      <RagAskPanel :documents="documents" />
    </div>
  </main>
</template>

<style scoped>
.knowledge-page {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  padding: 22px 26px 24px;
  overflow: hidden;
  background:
    radial-gradient(circle at 95% 3%, rgb(45 212 191 / 10%), transparent 23%),
    radial-gradient(circle at 4% 90%, rgb(147 197 253 / 8%), transparent 22%),
    #f4f8f7;
}

.knowledge-page::before {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgb(15 118 110 / 2.3%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(15 118 110 / 2.3%) 1px, transparent 1px);
  background-size: 36px 36px;
  mask-image: linear-gradient(to bottom, black, transparent 68%);
  content: "";
  pointer-events: none;
}

.knowledge-header {
  position: relative;
  z-index: 1;
  display: flex;
  flex: 0 0 auto;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 16px;
}

.knowledge-header h1 {
  margin: 0;
  color: #153c38;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  font-size: 27px;
  font-weight: 650;
  letter-spacing: -0.04em;
}

.knowledge-subtitle {
  margin: 5px 0 0;
  color: #7d918c;
  font-size: 10px;
}

.knowledge-grid {
  position: relative;
  z-index: 1;
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: minmax(310px, 0.8fr) minmax(0, 1.45fr);
  gap: 14px;
}

@media (max-width: 1050px) {
  .knowledge-page {
    padding: 18px;
    overflow-y: auto;
  }

  .knowledge-grid {
    flex: none;
    grid-template-columns: 1fr;
  }

  :deep(.rag-panel) {
    order: 1;
  }

  :deep(.library-panel) {
    order: 2;
  }
}

@media (max-width: 620px) {
  .knowledge-subtitle {
    max-width: 320px;
    line-height: 1.55;
  }
}
</style>

