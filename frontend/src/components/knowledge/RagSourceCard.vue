<script setup lang="ts">
import type { RagSource } from '../../types/knowledge'

defineProps<{
  source: RagSource
}>()
</script>

<template>
  <article class="source-card">
    <div class="source-head">
      <span class="citation-badge">{{ source.citation_id }}</span>
      <div class="source-title">
        <strong>{{ source.filename }}</strong>
        <span>
          {{ source.page_number === null ? '页码未知' : `第 ${source.page_number} 页` }}
          · 第 {{ source.part_index }} 个片段
        </span>
      </div>
    </div>

    <details class="source-details">
      <summary>查看引用片段</summary>
      <pre>{{ source.content_excerpt }}</pre>
    </details>
  </article>
</template>

<style scoped>
.source-card {
  min-width: 0;
  padding: 13px 14px;
  background: #f8fbfa;
  border: 1px solid #dfeae7;
  border-radius: 13px;
}

.source-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.citation-badge {
  display: grid;
  flex: 0 0 25px;
  place-items: center;
  width: 25px;
  height: 25px;
  color: #f0fdfa;
  background: #0f766e;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 750;
}

.source-title {
  min-width: 0;
}

.source-title strong {
  display: block;
  overflow: hidden;
  color: #274844;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-title span {
  display: block;
  margin-top: 3px;
  color: #849894;
  font-size: 10px;
}

.source-details {
  margin: 9px 0 0 35px;
}

.source-details summary {
  width: max-content;
  color: #397970;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.source-details pre {
  max-height: 220px;
  margin: 9px 0 0;
  padding: 11px;
  overflow: auto;
  color: #425b57;
  background: #fff;
  border: 1px solid #e6eeec;
  border-radius: 9px;
  font-family: inherit;
  font-size: 11px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

</style>

