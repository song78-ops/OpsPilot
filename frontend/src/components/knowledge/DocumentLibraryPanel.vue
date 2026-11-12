<script setup lang="ts">
import { ref } from 'vue'
import { ElButton, ElTag } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'

import type {
  DocumentDetail,
  DocumentIndexState,
  DocumentSummary,
} from '../../types/knowledge'

const props = defineProps<{
  documents: readonly DocumentSummary[]
  indexStates: Readonly<Record<string, DocumentIndexState>>
  selectedIds: readonly string[]
  selectedCount: number
  isLoading: boolean
  isUploading: boolean
  isIndexing: boolean
  error: string
  notice: string
  maxFileBytes: number
  refresh: () => Promise<void>
  uploadFile: (file: File) => Promise<DocumentDetail | null>
  toggleSelection: (documentId: string) => void
  indexSelected: () => Promise<unknown>
}>()

const emit = defineEmits<{
  clearMessages: []
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const pendingFile = ref<File | null>(null)
const isDragging = ref(false)

const statuses: Record<DocumentIndexState, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  unknown: { label: '索引状态不可知', type: 'info' },
  not_indexed: { label: '尚未索引', type: 'warning' },
  indexing: { label: '索引中', type: 'warning' },
  indexed: { label: '本次已索引', type: 'success' },
  error: { label: '索引失败', type: 'danger' },
}

function chooseFile() {
  if (!pendingFile.value) {
    return
  }
  emit('clearMessages')
  void submitUpload()
}

function openFilePicker() {
  fileInput.value?.click()
}

function handleInput(event: Event) {
  const target = event.target as HTMLInputElement
  pendingFile.value = target.files?.[0] ?? null
  target.value = ''
  emit('clearMessages')
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  pendingFile.value = event.dataTransfer?.files[0] ?? null
  emit('clearMessages')
}

async function submitUpload() {
  const file = pendingFile.value
  if (!file) {
    openFilePicker()
    return
  }
  const uploaded = await props.uploadFile(file)
  if (uploaded) {
    pendingFile.value = null
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <section class="library-panel">
    <header class="panel-heading">
      <div>
        <span class="panel-kicker">KNOWLEDGE CORPUS</span>
        <h2>文档库</h2>
      </div>
      <ElButton
        class="icon-button"
        :loading="isLoading"
        circle
        aria-label="刷新文档列表"
        @click="refresh"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path
            d="M15.9 6.1A7 7 0 1 0 17 11h-2a5 5 0 1 1-1-3l-2.2 2.2H17V5l-1.1 1.1Z"
          />
        </svg>
      </ElButton>
    </header>

    <div
      class="upload-zone"
      :class="{ 'upload-zone--active': isDragging }"
      @dragenter.prevent="isDragging = true"
      @dragover.prevent
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
    >
      <input
        ref="fileInput"
        class="file-input"
        type="file"
        accept=".pdf,.docx,.txt,.md,.markdown"
        data-testid="document-file-input"
        @change="handleInput"
      />
      <div class="upload-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path
            d="M11 4.4 6.3 9.1l1.4 1.4 2.3-2.3V16h2V8.2l2.3 2.3 1.4-1.4L11 4.4ZM5 17v2h12v-2H5Z"
          />
        </svg>
      </div>

      <template v-if="pendingFile">
        <strong class="file-name">{{ pendingFile.name }}</strong>
        <span class="upload-hint">
          {{ formatSize(pendingFile.size) }} · 上传后需单独建立索引
        </span>
      </template>
      <template v-else>
        <strong>拖入文档，或点击选择文件</strong>
        <span class="upload-hint">
          PDF / DOCX / TXT / Markdown · 前端限制 {{ Math.round(maxFileBytes / 1024 / 1024) }} MiB
        </span>
      </template>

      <div class="upload-actions">
        <ElButton
          v-if="!pendingFile"
          class="pick-button"
          native-type="button"
          @click="openFilePicker"
        >
          选择文件
        </ElButton>
        <template v-else>
          <ElButton text native-type="button" @click="pendingFile = null">
            取消
          </ElButton>
          <ElButton
            class="upload-button"
            type="primary"
            native-type="button"
            :loading="isUploading"
            data-testid="document-upload-button"
            @click="chooseFile"
          >
            上传文档
          </ElButton>
        </template>
      </div>
    </div>

    <div v-if="error" class="inline-message inline-message--error" role="alert">
      {{ error }}
    </div>
    <div v-if="notice" class="inline-message inline-message--notice">
      {{ notice }}
    </div>

    <div class="document-toolbar">
      <span>{{ documents.length }} 份文档 · 已选 {{ selectedCount }}</span>
      <ElButton
        class="index-button"
        type="primary"
        native-type="button"
        :disabled="selectedCount === 0"
        :loading="isIndexing"
        data-testid="index-selected-button"
        @click="indexSelected"
      >
        索引所选
      </ElButton>
    </div>

    <div class="document-list" data-testid="document-list">
      <div v-if="isLoading && documents.length === 0" class="empty-state">
        正在读取文档…
      </div>
      <div v-else-if="documents.length === 0" class="empty-state">
        还没有文档，先上传一份企业知识资料。
      </div>

      <article
        v-for="document in documents"
        :key="document.document_id"
        class="document-row"
        data-testid="document-row"
      >
        <input
          class="row-checkbox"
          type="checkbox"
          :checked="selectedIds.includes(document.document_id)"
          :aria-label="`选择 ${document.filename}`"
          @change="toggleSelection(document.document_id)"
        >
        <div class="document-file-icon" aria-hidden="true">
          {{ document.extension.replace('.', '').slice(0, 4).toUpperCase() }}
        </div>
        <div class="document-main">
          <strong :title="document.filename">{{ document.filename }}</strong>
          <span>
            {{ formatSize(document.file_size) }} · {{ document.chunk_count }} chunks
            · {{ formatDate(document.uploaded_at) }}
          </span>
          <code :title="document.document_id">{{ document.document_id }}</code>
          <ElTag
            size="small"
            effect="plain"
            :type="statuses[indexStates[document.document_id] ?? 'unknown'].type"
          >
            {{ statuses[indexStates[document.document_id] ?? 'unknown'].label }}
          </ElTag>
        </div>
      </article>
    </div>

    <p class="status-note">
      文档接口不返回持久化索引状态；“本次已索引”仅表示当前页面刚收到成功响应。
      刷新后状态显示为不可知，需要以检索结果为准。
    </p>
  </section>
</template>

<style scoped>
.library-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: 20px;
  overflow: hidden;
  background: rgb(255 255 255 / 78%);
  border: 1px solid #dce8e4;
  border-radius: 19px;
  box-shadow: 0 18px 50px rgb(20 60 55 / 7%);
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-kicker {
  color: #79918d;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.16em;
}

.panel-heading h2 {
  margin: 4px 0 0;
  color: #173f3b;
  font-size: 20px;
  font-weight: 650;
}

.icon-button {
  width: 32px;
  height: 32px;
  color: #54726d;
  border-color: #dce7e4;
}

.icon-button svg {
  width: 15px;
  height: 15px;
  fill: currentColor;
}

.upload-zone {
  display: flex;
  align-items: center;
  flex-direction: column;
  margin-top: 17px;
  padding: 18px 14px 14px;
  text-align: center;
  background:
    linear-gradient(145deg, rgb(240 253 250 / 76%), rgb(248 251 250 / 70%));
  border: 1px dashed #b7d7d1;
  border-radius: 15px;
  transition:
    border-color 160ms ease,
    background 160ms ease;
}

.upload-zone--active {
  background: #ecfdf8;
  border-color: #0f9f91;
}

.file-input {
  display: none;
}

.upload-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  margin-bottom: 8px;
  color: #27887d;
  background: #dcf5ef;
  border-radius: 11px;
}

.upload-icon svg {
  width: 20px;
  height: 20px;
  fill: currentColor;
}

.upload-zone strong {
  max-width: 100%;
  overflow: hidden;
  color: #32534f;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-name {
  direction: ltr;
}

.upload-hint {
  margin-top: 5px;
  color: #8ca09c;
  font-size: 9px;
  line-height: 1.5;
}

.upload-actions {
  display: flex;
  gap: 7px;
  margin-top: 12px;
}

.pick-button,
.upload-button {
  height: 30px;
  border-radius: 9px;
  font-size: 11px;
}

.upload-button {
  color: #fff;
  background: #0f766e;
  border-color: #0f766e;
}

.inline-message {
  margin-top: 9px;
  padding: 8px 10px;
  border-radius: 9px;
  font-size: 10px;
  line-height: 1.5;
}

.inline-message--error {
  color: #9b3d36;
  background: #fff4f1;
  border: 1px solid #f4d5cf;
}

.inline-message--notice {
  color: #25655d;
  background: #eefaf6;
  border: 1px solid #d7efe8;
}

.document-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 15px 0 8px;
  color: #80938f;
  font-size: 10px;
}

.index-button {
  height: 30px;
  border-radius: 9px;
  font-size: 10px;
}

.document-list {
  flex: 1;
  min-height: 0;
  padding-right: 3px;
  overflow-y: auto;
  scrollbar-color: rgb(15 118 110 / 20%) transparent;
  scrollbar-width: thin;
}

.document-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 11px 7px;
  border-top: 1px solid #e9efed;
}

.row-checkbox {
  flex: 0 0 auto;
  width: 14px;
  height: 14px;
  margin-top: 12px;
  accent-color: #0f766e;
}

.document-file-icon {
  display: grid;
  flex: 0 0 34px;
  place-items: center;
  width: 34px;
  height: 34px;
  color: #39766d;
  background: #eef5f3;
  border-radius: 9px;
  font-size: 8px;
  font-weight: 800;
}

.document-main {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: flex-start;
  flex-direction: column;
}

.document-main strong {
  max-width: 100%;
  overflow: hidden;
  color: #35514e;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-main > span {
  margin-top: 3px;
  color: #92a29f;
  font-size: 8px;
}

.document-main code {
  display: block;
  max-width: 100%;
  margin-top: 4px;
  overflow: hidden;
  color: #8a9c98;
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-main :deep(.el-tag) {
  height: 18px;
  margin-top: 6px;
  font-size: 8px;
}

.empty-state {
  display: grid;
  min-height: 100px;
  place-items: center;
  color: #8c9f9b;
  font-size: 10px;
  text-align: center;
}

.status-note {
  margin: 10px 0 0;
  padding-top: 9px;
  color: #94a39f;
  border-top: 1px solid #edf2f0;
  font-size: 8px;
  line-height: 1.55;
}

@media (max-width: 760px) {
  .library-panel {
    min-height: 520px;
    padding: 16px;
  }
}
</style>

