<script setup lang="ts">
import type { DeepReadonly } from 'vue'

import type { RagAskEntry } from '../../composables/useRagAsk'

import RagSourceCard from './RagSourceCard.vue'

defineProps<{
  entry: RagAskEntry | DeepReadonly<RagAskEntry>
}>()
</script>

<template>
  <article
    class="result-card"
    :class="{ 'result-card--insufficient': entry.response.status === 'insufficient_evidence' }"
    data-testid="rag-result"
  >
    <header class="result-header">
      <div>
        <span class="result-kicker">KNOWLEDGE ANSWER</span>
        <h3>{{ entry.question }}</h3>
      </div>
      <span
        class="status-pill"
        :class="`status-pill--${entry.response.status}`"
      >
        {{ entry.response.status === 'answered' ? '已回答' : '证据不足' }}
      </span>
    </header>

    <template v-if="entry.response.status === 'answered'">
      <div
        class="answer-text"
        data-testid="rag-answer"
      >{{ entry.response.answer }}</div>
    </template>

    <div v-else class="insufficient-box">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 3.1 21 19.4a1 1 0 0 1-.87 1.5H3.87A1 1 0 0 1 3 19.4L12 3.1Zm0 4.8a.9.9 0 0 0-.9.9v4.7a.9.9 0 1 0 1.8 0V8.8a.9.9 0 0 0-.9-.9Zm0 8.2a1.05 1.05 0 1 0 0 2.1 1.05 1.05 0 0 0 0-2.1Z"
        />
      </svg>
      <div>
        <strong>知识库中没有找到足够依据</strong>
        <p>{{ entry.response.reason || '当前证据不足以支持企业内部事实回答。' }}</p>
      </div>
    </div>

    <div
      v-if="entry.response.status === 'answered' && entry.response.reason"
      class="evidence-note"
    >
      <span>证据判断</span>
      <p>{{ entry.response.reason }}</p>
    </div>

    <div class="result-metrics">
      <span>{{ entry.response.retrieval_mode.toUpperCase() }}</span>
      <span>{{ entry.response.rerank_applied ? '已精排' : '未精排' }}</span>
      <span>{{ entry.response.retrieval_count }} 个候选</span>
      <span>{{ entry.response.latency_ms.total_ms.toFixed(0) }} ms</span>
      <span v-if="entry.response.usage">
        {{ entry.response.usage.prompt_tokens }} + {{ entry.response.usage.completion_tokens }} tokens
      </span>
    </div>

    <div v-if="entry.response.sources.length > 0" class="sources">
      <p class="sources-label">引用来源</p>
      <div class="source-grid">
        <RagSourceCard
          v-for="source in entry.response.sources"
          :key="source.chunk_id + source.part_index"
          :source="source"
        />
      </div>
    </div>

    <details class="latency-details">
      <summary>查看阶段耗时</summary>
      <div>
        <span>检索 {{ entry.response.latency_ms.retrieval_ms.toFixed(1) }} ms</span>
        <span>上下文 {{ entry.response.latency_ms.context_ms.toFixed(1) }} ms</span>
        <span>生成 {{ entry.response.latency_ms.generation_ms.toFixed(1) }} ms</span>
        <span>总计 {{ entry.response.latency_ms.total_ms.toFixed(1) }} ms</span>
      </div>
    </details>
  </article>
</template>

<style scoped>
.result-card {
  padding: 20px;
  background: rgb(255 255 255 / 86%);
  border: 1px solid #dde8e5;
  border-radius: 18px;
  box-shadow: 0 14px 40px rgb(25 68 63 / 7%);
}

.result-card--insufficient {
  background: #fffdf8;
  border-color: #ecdcc2;
}

.result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.result-kicker {
  color: #73908b;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.16em;
}

.result-header h3 {
  margin: 6px 0 0;
  color: #183e3a;
  font-size: 15px;
  font-weight: 650;
  line-height: 1.5;
}

.status-pill {
  flex: 0 0 auto;
  padding: 5px 9px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
}

.status-pill--answered {
  color: #16685e;
  background: #e9f9f4;
  border: 1px solid #bcebdf;
}

.status-pill--insufficient_evidence {
  color: #98600c;
  background: #fff5df;
  border: 1px solid #efd9ae;
}

.answer-text {
  margin-top: 18px;
  color: #294642;
  font-size: 14px;
  line-height: 1.9;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.insufficient-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 17px;
  padding: 14px;
  color: #815917;
  background: #fff8e9;
  border: 1px solid #efdfc0;
  border-radius: 13px;
}

.insufficient-box svg {
  flex: 0 0 20px;
  width: 20px;
  height: 20px;
  fill: #d38b1e;
}

.insufficient-box strong {
  font-size: 12px;
}

.insufficient-box p {
  margin: 5px 0 0;
  font-size: 11px;
  line-height: 1.65;
}

.evidence-note {
  margin-top: 12px;
  padding: 10px 12px;
  color: #657b77;
  background: #f7faf9;
  border-left: 2px solid #80b9af;
  border-radius: 0 9px 9px 0;
}

.evidence-note span {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.evidence-note p {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.65;
}

.result-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 15px;
}

.result-metrics span {
  padding: 4px 8px;
  color: #78908c;
  background: #f4f8f7;
  border-radius: 7px;
  font-size: 9px;
}

.sources {
  margin-top: 18px;
}

.sources-label {
  margin: 0 0 8px;
  color: #708984;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.source-grid {
  display: grid;
  gap: 8px;
}

.latency-details {
  margin-top: 13px;
  color: #8b9d99;
  font-size: 9px;
}

.latency-details summary {
  width: max-content;
  cursor: pointer;
}

.latency-details div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 7px;
}

@media (max-width: 560px) {
  .result-card {
    padding: 15px;
    border-radius: 15px;
  }
}
</style>

