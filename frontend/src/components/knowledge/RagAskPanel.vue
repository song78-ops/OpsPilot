<script setup lang="ts">
import {
  nextTick,
  ref,
  watch,
} from 'vue'
import { ElButton, ElSwitch } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/switch/style/css'

import { useRagAsk } from '../../composables/useRagAsk'
import type {
  DocumentSummary,
  RetrievalMode,
} from '../../types/knowledge'
import RagResultCard from './RagResultCard.vue'

const props = defineProps<{
  documents: readonly DocumentSummary[]
}>()

const {
  question,
  mode,
  rerank,
  topK,
  candidateK,
  documentId,
  isAsking,
  error,
  entries,
  ask,
  clearHistory,
} = useRagAsk()

const resultViewport = ref<HTMLElement | null>(null)
const modes: Array<{ value: RetrievalMode; label: string; detail: string }> = [
  { value: 'dense', label: 'Dense', detail: '语义向量' },
  { value: 'bm25', label: 'BM25', detail: '关键词' },
  { value: 'hybrid', label: 'Hybrid', detail: 'RRF 融合' },
]

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    void ask()
  }
}

watch(
  () => entries.value.length,
  async () => {
    await nextTick()
    resultViewport.value?.scrollTo({
      top: resultViewport.value.scrollHeight,
      behavior: 'smooth',
    })
  },
)
</script>

<template>
  <section class="rag-panel">
    <header class="rag-heading">
      <div>
        <span class="rag-kicker">GROUNDED ASSISTANT</span>
        <h2>知识库问答</h2>
        <p>回答只依据后端检索证据，并返回可核验引用。</p>
      </div>
      <ElButton
        v-if="entries.length > 0"
        text
        :disabled="isAsking"
        @click="clearHistory"
      >
        清空结果
      </ElButton>
    </header>

    <div class="settings-row">
      <div class="mode-switch" role="group" aria-label="检索模式">
        <button
          v-for="item in modes"
          :key="item.value"
          type="button"
          :class="{ active: mode === item.value }"
          :data-testid="`rag-mode-${item.value}`"
          @click="mode = item.value"
        >
          <strong>{{ item.label }}</strong>
          <span>{{ item.detail }}</span>
        </button>
      </div>

      <label class="rerank-toggle">
        <ElSwitch v-model="rerank" data-testid="rag-rerank-switch" />
        <span>
          <strong>CrossEncoder 精排</strong>
          <small>延迟较高，默认关闭</small>
        </span>
      </label>
    </div>

    <div class="parameter-row">
      <label>
        <span>Top-K</span>
        <input v-model.number="topK" type="number" min="1" max="20">
      </label>
      <label v-if="rerank">
        <span>候选数</span>
        <input
          v-model.number="candidateK"
          type="number"
          :min="topK"
          max="20"
          data-testid="rag-candidate-k"
        >
      </label>
      <label class="scope-field">
        <span>检索范围</span>
        <select v-model="documentId">
          <option :value="null">全部已索引文档</option>
          <option
            v-for="document in props.documents"
            :key="document.document_id"
            :value="document.document_id"
          >
            {{ document.filename }}
          </option>
        </select>
      </label>
    </div>

    <div ref="resultViewport" class="result-viewport">
      <div v-if="entries.length === 0" class="rag-welcome">
        <div class="rag-welcome-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32">
            <path
              d="M8 4h13l5 5v19H8V4Zm12 2v5h5l-5-5ZM11 14h10v2H11v-2Zm0 5h10v2H11v-2Zm0 5h7v2h-7v-2Z"
            />
          </svg>
        </div>
        <strong>向企业知识库提问</strong>
        <p>系统会先检索文档，再生成带引用的回答。证据不足时会明确拒答。</p>
        <div class="example-questions">
          <span>可以试试：</span>
          <button
            type="button"
            @click="question = '缓存击穿应该怎么处理？'"
          >
            缓存击穿应该怎么处理？
          </button>
          <button
            type="button"
            @click="question = '怎样保证订单数据库的一致性？'"
          >
            怎样保证订单数据库的一致性？
          </button>
        </div>
      </div>

      <div v-else class="result-list">
        <RagResultCard
          v-for="entry in entries"
          :key="entry.id"
          :entry="entry"
        />
      </div>
    </div>

    <div v-if="error" class="rag-error" role="alert" data-testid="rag-error">
      {{ error }}
    </div>
    <div v-if="isAsking" class="asking-state" aria-live="polite">
      <span class="asking-spinner" />
      正在检索知识库并生成回答，请稍候…
    </div>

    <div class="ask-composer">
      <textarea
        v-model="question"
        rows="3"
        maxlength="4000"
        placeholder="输入需要基于企业知识回答的问题…"
        data-testid="rag-question-input"
        :disabled="isAsking"
        @keydown="handleKeydown"
      />
      <div class="composer-foot">
        <span>仅发送当前问题 · Ctrl + Enter 提交</span>
        <ElButton
          class="ask-button"
          type="primary"
          native-type="button"
          :disabled="!question.trim() || isAsking"
          :loading="isAsking"
          data-testid="rag-ask-button"
          @click="ask"
        >
          询问知识库
        </ElButton>
      </div>
    </div>
  </section>
</template>

<style scoped>
.rag-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  padding: 22px;
  background:
    radial-gradient(circle at 88% 5%, rgb(45 212 191 / 8%), transparent 24%),
    rgb(251 253 252 / 82%);
  border: 1px solid #dce8e4;
  border-radius: 19px;
  box-shadow: 0 18px 50px rgb(20 60 55 / 7%);
}

.rag-heading {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.rag-kicker {
  color: #75938e;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.17em;
}

.rag-heading h2 {
  margin: 4px 0 3px;
  color: #173f3b;
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.03em;
}

.rag-heading p {
  margin: 0;
  color: #849692;
  font-size: 10px;
}

.settings-row {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
}

.mode-switch {
  display: grid;
  flex: 1;
  max-width: 390px;
  padding: 3px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  background: #edf4f2;
  border-radius: 12px;
}

.mode-switch button {
  display: flex;
  min-height: 43px;
  flex-direction: column;
  justify-content: center;
  padding: 5px 8px;
  color: #7e918d;
  background: transparent;
  border: 0;
  border-radius: 9px;
  cursor: pointer;
}

.mode-switch button.active {
  color: #225e56;
  background: #fff;
  box-shadow: 0 4px 13px rgb(38 88 81 / 8%);
}

.mode-switch strong {
  font-size: 11px;
}

.mode-switch span {
  margin-top: 2px;
  font-size: 8px;
}

.rerank-toggle {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 9px;
  padding: 0 11px;
  background: #f8fbfa;
  border: 1px solid #e3ece9;
  border-radius: 12px;
}

.rerank-toggle strong,
.rerank-toggle small {
  display: block;
}

.rerank-toggle strong {
  color: #506c68;
  font-size: 10px;
}

.rerank-toggle small {
  margin-top: 2px;
  color: #94a39f;
  font-size: 8px;
}

.parameter-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  margin-top: 12px;
}

.parameter-row label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.parameter-row label > span {
  color: #849692;
  font-size: 8px;
}

.parameter-row input,
.parameter-row select {
  height: 31px;
  color: #42625e;
  background: #fff;
  border: 1px solid #dce7e4;
  border-radius: 8px;
  font-size: 10px;
}

.parameter-row input {
  width: 66px;
  padding: 0 8px;
}

.parameter-row select {
  min-width: 190px;
  padding: 0 9px;
}

.scope-field {
  margin-left: auto;
}

.scope-field select {
  max-width: 260px;
}

.result-viewport {
  flex: 1;
  min-height: 0;
  margin-top: 14px;
  padding-right: 4px;
  overflow-y: auto;
  scrollbar-color: rgb(15 118 110 / 20%) transparent;
  scrollbar-width: thin;
}

.rag-welcome {
  display: flex;
  min-height: 100%;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  padding: 25px;
  text-align: center;
}

.rag-welcome-mark {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  color: #0f766e;
  background: #e8f6f2;
  border: 1px solid #cce9e1;
  border-radius: 17px;
}

.rag-welcome-mark svg {
  width: 27px;
  height: 27px;
  fill: currentColor;
}

.rag-welcome strong {
  margin-top: 13px;
  color: #31544f;
  font-size: 16px;
}

.rag-welcome p {
  max-width: 430px;
  margin: 7px 0 0;
  color: #879994;
  font-size: 11px;
  line-height: 1.7;
}

.example-questions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 16px;
}

.example-questions span {
  color: #98a5a2;
  font-size: 9px;
}

.example-questions button {
  padding: 6px 9px;
  color: #4e756f;
  background: #fff;
  border: 1px solid #dce8e5;
  border-radius: 8px;
  font-size: 9px;
  cursor: pointer;
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 6px;
}

.rag-error {
  margin-top: 9px;
  padding: 9px 11px;
  color: #9d3e37;
  background: #fff4f1;
  border: 1px solid #f3d4ce;
  border-radius: 9px;
  font-size: 10px;
}

.asking-state {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 9px;
  color: #49756e;
  font-size: 10px;
}

.asking-spinner {
  width: 13px;
  height: 13px;
  border: 2px solid #cbe9e2;
  border-top-color: #0f9f91;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.ask-composer {
  flex: 0 0 auto;
  margin-top: 10px;
  padding: 11px;
  background: #fff;
  border: 1px solid #d7e4e1;
  border-radius: 14px;
  box-shadow: 0 8px 24px rgb(29 72 67 / 7%);
}

.ask-composer:focus-within {
  border-color: rgb(13 148 136 / 50%);
  box-shadow: 0 0 0 3px rgb(13 148 136 / 7%);
}

.ask-composer textarea {
  display: block;
  width: 100%;
  min-height: 62px;
  resize: none;
  color: #2f4e4a;
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 12px;
  line-height: 1.7;
}

.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.composer-foot > span {
  color: #98a6a2;
  font-size: 8px;
}

.ask-button {
  height: 30px;
  padding-inline: 13px;
  color: #fff;
  background: #0f766e;
  border-color: #0f766e;
  border-radius: 9px;
  font-size: 10px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 760px) {
  .rag-panel {
    min-height: 620px;
    padding: 16px;
  }

  .settings-row {
    flex-direction: column;
  }

  .mode-switch {
    max-width: none;
  }

  .rerank-toggle {
    min-height: 48px;
    justify-content: space-between;
  }

  .parameter-row {
    flex-wrap: wrap;
  }

  .scope-field {
    width: 100%;
    margin-left: 0;
  }

  .scope-field select {
    width: 100%;
    max-width: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .asking-spinner {
    animation: none;
  }
}
</style>

