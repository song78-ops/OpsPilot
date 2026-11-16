<script setup lang="ts">
import { computed } from 'vue'
import type { DeepReadonly } from 'vue'

import type {
  AgentRunResponse,
  ConversationMessage,
} from '../../types/agent'
import RagSourceCard from '../knowledge/RagSourceCard.vue'

const props = defineProps<{
  messages:
    | readonly ConversationMessage[]
    | DeepReadonly<ConversationMessage[]>
  latestResult: AgentRunResponse | DeepReadonly<AgentRunResponse> | null
  isLoading: boolean
}>()

const visibleMessages = computed(() => (
  props.messages.filter((message) => message.role !== 'tool')
))
const toolMessages = computed(() => (
  props.messages.filter((message) => message.role === 'tool')
))

const statusLabels: Record<string, string> = {
  completed: '已完成',
  insufficient_evidence: '缺少足够依据',
  ticket_draft_ready: '工单已更新',
  needs_clarification: '需要补充信息',
  service_error: '请求失败',
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatDuration(value: number): string {
  return value < 1 ? '<1 ms' : `${value.toFixed(1)} ms`
}

function displayMessage(content: string): string {
  return content
    .replace(/<\/?evidence[^>]*>/gi, '')
    .replace(
      /工单草稿已保存，ID:\s*[0-9a-f]{32}。/g,
      '工单已保存，可在右侧查看和继续处理。',
    )
    .replace(
      /工单草稿\s*[0-9a-f]{32}\s*已更新，尚未创建正式工单。/g,
      '工单已更新，可在右侧查看最新内容。',
    )
    .replace(
      /该工具调用已存在，返回工单草稿 ID:\s*[0-9a-f]{32}。/g,
      '工单已保存，可在右侧查看。',
    )
    .replace(
      /已查询到工单草稿 ID:\s*[0-9a-f]{32}。/g,
      '已找到这份工单。',
    )
}
</script>

<template>
  <div v-if="isLoading" class="timeline-loading">
    正在从服务端加载会话历史…
  </div>
  <div v-else-if="messages.length === 0" class="timeline-welcome">
    <div class="welcome-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32">
        <path
          d="M8 5h12l5 5v17H8V5Zm11 2v5h5l-5-5ZM11 15h10v2H11v-2Zm0 5h10v2H11v-2Z"
        />
      </svg>
    </div>
    <strong>有什么可以帮你处理？</strong>
    <p>
      描述你遇到的问题，可以在这里创建工单、修改内容并跟进审批。
    </p>
  </div>

  <div v-else class="timeline" data-testid="agent-message-timeline">
    <article
      v-for="message in visibleMessages"
      :key="message.id"
      class="timeline-message"
      :class="`timeline-message--${message.role}`"
      :data-role="message.role"
      data-testid="agent-history-message"
    >
      <div class="message-meta">
        <strong>{{ message.role === 'user' ? '你' : '工单助手' }}</strong>
        <span>{{ formatTime(message.created_at) }}</span>
        <span v-if="message.status" class="message-status">
          {{ statusLabels[message.status] ?? message.status }}
        </span>
      </div>
      <p class="message-text">{{ displayMessage(message.content) }}</p>
    </article>

    <section
      v-if="latestResult?.sources.length"
      class="source-summary"
    >
      <h4>参考来源</h4>
      <RagSourceCard
        v-for="source in latestResult.sources"
        :key="`${source.chunk_id}:${source.part_index}`"
        :source="source"
      />
    </section>

    <section
      v-if="latestResult"
      class="run-shell"
    >
      <details class="run-details" data-testid="agent-current-run">
        <summary>
          运行详情
          <small>查看处理过程</small>
        </summary>

        <div class="run-summary">
          <span>
            处理结果：
            <em data-testid="agent-current-intent">
              {{ latestResult.intent }}
            </em>
          </span>
          <span>{{ latestResult.latency_ms.toFixed(0) }} ms</span>
        </div>

        <div
          v-for="message in toolMessages"
          :key="message.id"
          class="tool-summary"
          data-testid="agent-tool-summary"
        >
          <span class="tool-icon">✓</span>
          <div>
            <strong>{{ message.tool_name }}</strong>
            <p>{{ message.content }}</p>
            <small>{{ statusLabels[message.tool_status ?? ''] ?? message.tool_status }}</small>
          </div>
        </div>

        <p>
          处理步骤：
          {{ latestResult.executed_nodes.join(' → ') || '无' }}
        </p>
        <div
          v-for="trace in latestResult.node_traces"
          :key="`${trace.node}-${trace.duration_ms}`"
          class="trace-row"
        >
          <code>{{ trace.node }}</code>
          <span>{{ trace.status }}</span>
          <strong>{{ formatDuration(trace.duration_ms) }}</strong>
        </div>
        <div
          v-for="call in latestResult.tool_calls"
          :key="call.tool_call_id"
          class="trace-row trace-row--tool"
        >
          <code>{{ call.name }}</code>
          <span>{{ call.status }}</span>
          <strong>{{ formatDuration(call.duration_ms) }}</strong>
        </div>
      </details>
    </section>
  </div>
</template>

<style scoped>
.timeline-loading,
.timeline-welcome {
  display: flex;
  min-height: 100%;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  padding: 22px 12px;
  color: #879b96;
  font-size: 11px;
  text-align: center;
}

.welcome-mark {
  display: grid;
  place-items: center;
  width: 50px;
  height: 50px;
  color: #0f766e;
  background: #e7f7f2;
  border: 1px solid #ccebe2;
  border-radius: 16px;
}

.welcome-mark svg {
  width: 26px;
  height: 26px;
  fill: currentColor;
}

.timeline-welcome strong {
  margin-top: 13px;
  color: #31534f;
  font-size: 16px;
}

.timeline-welcome p {
  max-width: 370px;
  margin: 7px 0 0;
  line-height: 1.75;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 3px;
}

.timeline-message {
  max-width: 92%;
}

.timeline-message--user {
  align-self: flex-end;
  padding: 10px 12px;
  color: #effdfa;
  background: linear-gradient(145deg, #0f766e, #115f58);
  border-radius: 14px 14px 4px 14px;
  box-shadow: 0 8px 20px rgb(15 118 110 / 14%);
}

.timeline-message--assistant {
  align-self: flex-start;
  padding: 11px 12px;
  color: #2f4f4a;
  background: #fff;
  border: 1px solid #dde8e5;
  border-radius: 4px 14px 14px;
  box-shadow: 0 8px 20px rgb(22 68 62 / 6%);
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #89a19c;
  font-size: 9px;
}

.timeline-message--user .message-meta {
  color: #a8ded5;
}

.message-meta strong {
  font-size: 10px;
}

.message-status {
  margin-left: auto;
  padding: 2px 5px;
  background: rgb(15 118 110 / 7%);
  border-radius: 999px;
}

.message-text {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.tool-summary {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 9px;
  color: #607a74;
  background: #f5faf8;
  border: 1px solid #e1ebe8;
  border-left: 2px solid #78b7ac;
  border-radius: 0 8px 8px 0;
}

.tool-icon {
  display: grid;
  flex: 0 0 20px;
  place-items: center;
  width: 20px;
  height: 20px;
  color: #3b887d;
  background: #e7f6f2;
  border-radius: 6px;
  font-size: 9px;
}

.tool-summary strong {
  font-size: 10px;
}

.tool-summary p {
  margin: 3px 0;
  font-size: 10px;
  line-height: 1.5;
}

.tool-summary small {
  color: #8fa29e;
  font-size: 9px;
  overflow-wrap: anywhere;
}

.source-summary {
  display: grid;
  gap: 6px;
}

.source-summary h4 {
  margin: 0;
  color: #52716b;
  font-size: 11px;
}

.run-shell {
  margin-top: 2px;
}

.run-details {
  padding: 10px 11px;
  color: #6f8883;
  background: #f8fbfa;
  border: 1px solid #e2ebe8;
  border-radius: 11px;
  font-size: 10px;
}

.run-details summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #496761;
  font-weight: 600;
  cursor: pointer;
}

.run-details summary small {
  color: #91a29e;
  font-size: 9px;
  font-weight: 400;
}

.run-summary {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 9px;
}

.run-summary em {
  color: #34776d;
  font-style: normal;
}

.run-details > p {
  margin: 8px 0;
  line-height: 1.55;
}

.trace-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 7px;
  margin-top: 4px;
  padding: 5px 7px;
  background: #fff;
  border-radius: 6px;
}

.trace-row code {
  overflow: hidden;
  text-overflow: ellipsis;
}

.trace-row span,
.trace-row strong {
  color: #92a29f;
  font-size: 7px;
  font-weight: 500;
}

.trace-row--tool {
  border-left: 2px solid #9bcbc2;
}
</style>
