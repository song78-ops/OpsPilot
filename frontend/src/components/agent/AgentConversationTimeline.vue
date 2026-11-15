<script setup lang="ts">
import type { DeepReadonly } from 'vue'

import type {
  AgentRunResponse,
  ConversationMessage,
} from '../../types/agent'
import RagSourceCard from '../knowledge/RagSourceCard.vue'

defineProps<{
  messages:
    | readonly ConversationMessage[]
    | DeepReadonly<ConversationMessage[]>
  latestResult: AgentRunResponse | DeepReadonly<AgentRunResponse> | null
  isLoading: boolean
}>()

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatDuration(value: number): string {
  return value < 1 ? '<1 ms' : `${value.toFixed(1)} ms`
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
    <strong>开始一个新的 Agent 会话</strong>
    <p>
      首次发送后后端生成 conversation_id。之后的请求会自动携带它，
      并从这里恢复服务端消息记录。
    </p>
  </div>

  <div v-else class="timeline" data-testid="agent-message-timeline">
    <article
      v-for="message in messages"
      :key="message.id"
      class="timeline-message"
      :class="`timeline-message--${message.role}`"
      :data-role="message.role"
      data-testid="agent-history-message"
    >
      <template v-if="message.role === 'tool'">
        <div class="tool-summary" data-testid="agent-tool-summary">
          <span class="tool-icon">⚙</span>
          <div>
            <strong>{{ message.tool_name || 'tool' }}</strong>
            <p>{{ message.content }}</p>
            <small>
              {{ message.tool_status || 'unknown' }}
              <template v-if="message.business_reference_id">
                · {{ message.business_reference_id }}
              </template>
            </small>
          </div>
        </div>
      </template>
      <template v-else>
        <div class="message-meta">
          <strong>{{ message.role === 'user' ? '你' : 'OpsPilot' }}</strong>
          <span>{{ formatTime(message.created_at) }}</span>
          <span v-if="message.status" class="message-status">
            {{ message.status }}
          </span>
        </div>
        <p class="message-text">{{ message.content }}</p>
      </template>
    </article>

    <section
      v-if="latestResult"
      class="run-details"
      data-testid="agent-current-run"
    >
      <header>
        <div>
          <span>CURRENT RUN</span>
          <strong>
            本次运行摘要 ·
            <em data-testid="agent-current-intent">
              {{ latestResult.intent }}
            </em>
          </strong>
        </div>
        <small>{{ latestResult.latency_ms.toFixed(0) }} ms</small>
      </header>

      <div v-if="latestResult.sources.length > 0" class="run-sources">
        <RagSourceCard
          v-for="source in latestResult.sources"
          :key="`${source.chunk_id}:${source.part_index}`"
          :source="source"
        />
      </div>

      <details>
        <summary>查看节点和工具调用</summary>
        <p>
          节点：
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
  font-size: 9px;
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
  font-size: 14px;
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
  font-size: 7px;
}

.timeline-message--user .message-meta {
  color: #a8ded5;
}

.message-meta strong {
  font-size: 8px;
}

.message-status {
  margin-left: auto;
  padding: 2px 5px;
  background: rgb(15 118 110 / 7%);
  border-radius: 999px;
}

.message-text {
  margin: 6px 0 0;
  font-size: 11px;
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
  font-size: 8px;
}

.tool-summary p {
  margin: 3px 0;
  font-size: 8px;
  line-height: 1.5;
}

.tool-summary small {
  color: #8fa29e;
  font-size: 7px;
  overflow-wrap: anywhere;
}

.run-details {
  margin-top: 4px;
  padding: 11px;
  background: #f8fbfa;
  border: 1px solid #e2ebe8;
  border-radius: 11px;
}

.run-details header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.run-details header span,
.run-details header strong {
  display: block;
}

.run-details header em {
  color: #43847a;
  font-size: 8px;
  font-style: normal;
  letter-spacing: 0.03em;
}

.run-details header span {
  color: #8aa09b;
  font-size: 7px;
  letter-spacing: 0.12em;
}

.run-details header strong {
  margin-top: 3px;
  color: #486660;
  font-size: 10px;
}

.run-details header small {
  color: #8da09c;
  font-size: 8px;
}

.run-sources {
  display: grid;
  gap: 6px;
  margin-top: 9px;
}

.run-details details {
  margin-top: 9px;
  color: #7d918c;
  font-size: 8px;
}

.run-details summary {
  cursor: pointer;
}

.run-details details > p {
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
