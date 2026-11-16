<script setup lang="ts">
import type { DeepReadonly } from 'vue'

import type { AgentIntent, AgentRunResponse } from '../../types/agent'
import RagSourceCard from '../knowledge/RagSourceCard.vue'

defineProps<{
  result: AgentRunResponse | DeepReadonly<AgentRunResponse>
}>()

const emit = defineEmits<{
  openDraft: [draftId: string]
}>()

const intentLabels: Record<AgentIntent, string> = {
  knowledge_query: '企业知识库',
  ticket_request: '工单请求',
  general_chat: '普通聊天',
  clarification: '需要补充',
}

const statusLabels: Record<AgentRunResponse['status'], string> = {
  completed: '已完成',
  insufficient_evidence: '证据不足',
  ticket_draft_ready: '草稿已保存',
  needs_clarification: '需要补充',
}
const draftStatusLabels: Record<string, string> = {
  draft: '草稿',
  pending_approval: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
}

function formatDuration(value: number): string {
  return value < 1 ? '<1 ms' : `${value.toFixed(1)} ms`
}
</script>

<template>
  <article
    class="agent-result"
    :class="`agent-result--${result.intent}`"
    data-testid="agent-result"
  >
    <header class="result-heading">
      <div>
        <div class="intent-line">
          <h3>{{ intentLabels[result.intent] }}</h3>
          <span class="status-chip">{{ statusLabels[result.status] }}</span>
        </div>
      </div>
      <span class="latency">{{ result.latency_ms.toFixed(0) }} ms</span>
    </header>

    <div
      v-if="result.answer"
      class="answer-text"
      data-testid="agent-answer"
    >{{ result.answer }}</div>
    <div v-else class="empty-answer">
      Agent 没有返回可展示的文本，请查看运行摘要或补充信息。
    </div>

    <div
      v-if="result.status === 'insufficient_evidence'"
      class="evidence-warning"
    >
      知识库没有足够依据回答该问题。系统没有降级为无依据的普通聊天。
    </div>

    <div v-if="result.error" class="agent-warning">
      运行提示：{{ result.error }}
    </div>

    <div v-if="result.sources.length > 0" class="sources">
      <p class="section-label">知识库引用</p>
      <RagSourceCard
        v-for="source in result.sources"
        :key="`${source.chunk_id}:${source.part_index}`"
        :source="source"
      />
    </div>

    <section
      v-if="result.ticket_draft"
      class="draft-card"
      data-testid="agent-draft-card"
    >
      <div class="draft-card__top">
        <div>
          <span>真实持久化工单草稿</span>
          <h4>{{ result.ticket_draft.title }}</h4>
        </div>
        <span class="draft-status">
          {{ draftStatusLabels[result.ticket_draft.status] }}
        </span>
      </div>
      <p>{{ result.ticket_draft.description }}</p>
      <dl>
        <div>
          <dt>设备 / 系统</dt>
          <dd>{{ result.ticket_draft.device_or_system }}</dd>
        </div>
      </dl>
      <button
        type="button"
        data-testid="agent-open-draft"
        @click="emit('openDraft', result.ticket_draft.id)"
      >
        查看这份工单
      </button>
    </section>

    <details class="execution-details" data-testid="agent-execution">
      <summary>
        运行详情
        <span>{{ result.executed_nodes.length }} 个节点</span>
      </summary>

      <div class="execution-grid">
        <div>
          <span class="section-label">执行节点</span>
          <ol class="node-list">
            <li v-for="(node, index) in result.executed_nodes" :key="`${node}-${index}`">
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              {{ node }}
            </li>
          </ol>
        </div>

        <div>
          <span class="section-label">节点耗时</span>
          <div class="trace-list">
            <div v-for="trace in result.node_traces" :key="`${trace.node}-${trace.duration_ms}`">
              <code>{{ trace.node }}</code>
              <span>{{ trace.status }}</span>
              <strong>{{ formatDuration(trace.duration_ms) }}</strong>
            </div>
          </div>
        </div>
      </div>

      <div v-if="result.tool_calls.length > 0" class="tool-list">
        <span class="section-label">工具调用</span>
        <div v-for="call in result.tool_calls" :key="call.tool_call_id">
          <code>{{ call.name }}</code>
          <span>{{ call.status }}</span>
          <strong>{{ formatDuration(call.duration_ms) }}</strong>
        </div>
      </div>

      <p class="runtime-note">
        处理说明：{{ result.supervisor_reason }}
        <template v-if="result.model"> · 模型 {{ result.model }}</template>
      </p>
    </details>
  </article>
</template>

<style scoped>
.agent-result {
  padding: 17px;
  background: rgb(255 255 255 / 88%);
  border: 1px solid #dbe8e4;
  border-radius: 16px;
  box-shadow: 0 14px 34px rgb(27 68 63 / 7%);
}

.result-heading,
.intent-line,
.draft-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.section-label {
  color: #7a938e;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.intent-line {
  justify-content: flex-start;
  margin-top: 4px;
}

.intent-line h3 {
  margin: 0;
  color: #173e3a;
  font-size: 16px;
}

.status-chip,
.draft-status {
  padding: 3px 7px;
  color: #267167;
  background: #edfaf6;
  border: 1px solid #ccece4;
  border-radius: 999px;
  font-size: 8px;
}

.latency {
  color: #8aa09b;
  font-size: 9px;
}

.answer-text {
  margin-top: 14px;
  color: #2b4a46;
  font-size: 13px;
  line-height: 1.85;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.empty-answer,
.evidence-warning,
.agent-warning {
  margin-top: 12px;
  padding: 10px 11px;
  color: #7a6850;
  background: #fff9eb;
  border: 1px solid #eedfbe;
  border-radius: 10px;
  font-size: 10px;
  line-height: 1.6;
}

.agent-warning {
  color: #8b4941;
  background: #fff4f1;
  border-color: #f1d6d0;
}

.sources {
  display: grid;
  gap: 8px;
  margin-top: 15px;
}

.draft-card {
  margin-top: 15px;
  padding: 13px;
  background:
    linear-gradient(145deg, rgb(236 253 245 / 72%), rgb(248 252 250 / 92%));
  border: 1px solid #cfe7df;
  border-radius: 13px;
}

.draft-card__top {
  align-items: flex-start;
}

.draft-card__top span:first-child {
  color: #64847e;
  font-size: 8px;
}

.draft-card h4 {
  margin: 4px 0 0;
  color: #1d4843;
  font-size: 14px;
}

.draft-card > p {
  margin: 9px 0;
  color: #55716d;
  font-size: 10px;
  line-height: 1.65;
}

.draft-card dl {
  display: grid;
  gap: 6px;
  margin: 0;
}

.draft-card dl div {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 8px;
}

.draft-card dt {
  color: #829590;
  font-size: 8px;
}

.draft-card dd {
  min-width: 0;
  margin: 0;
  color: #466761;
  font-size: 9px;
  overflow-wrap: anywhere;
}

.draft-card code {
  font-size: 8px;
}

.draft-card button {
  margin-top: 11px;
  padding: 6px 9px;
  color: #176d63;
  background: #fff;
  border: 1px solid #bcded6;
  border-radius: 8px;
  font-size: 9px;
  cursor: pointer;
}

.execution-details {
  margin-top: 13px;
  color: #728985;
  font-size: 9px;
}

.execution-details summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}

.execution-details summary span {
  color: #92a29f;
}

.execution-grid {
  display: grid;
  grid-template-columns: 0.8fr 1.2fr;
  gap: 15px;
  margin-top: 12px;
}

.node-list {
  display: grid;
  gap: 5px;
  margin: 7px 0 0;
  padding: 0;
  list-style: none;
}

.node-list li {
  display: flex;
  gap: 7px;
  color: #55716c;
}

.node-list li span {
  color: #9cafab;
  font-size: 7px;
}

.trace-list,
.tool-list {
  display: grid;
  gap: 5px;
  margin-top: 7px;
}

.trace-list div,
.tool-list div {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 7px;
  padding: 5px 7px;
  background: #f6faf8;
  border-radius: 6px;
}

.trace-list code,
.tool-list code {
  overflow: hidden;
  color: #476660;
  font-size: 8px;
  text-overflow: ellipsis;
}

.trace-list span,
.tool-list span,
.trace-list strong,
.tool-list strong {
  color: #8c9d99;
  font-size: 8px;
  font-weight: 500;
}

.tool-list {
  margin-top: 12px;
}

.runtime-note {
  margin: 11px 0 0;
  color: #92a09d;
  font-size: 8px;
  line-height: 1.55;
}

@media (max-width: 520px) {
  .execution-grid {
    grid-template-columns: 1fr;
  }
}
</style>
