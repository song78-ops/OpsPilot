<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { DeepReadonly } from 'vue'
import { ElButton, ElTag } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'

import type {
  AgentRunResponse,
  ConversationMessage,
} from '../../types/agent'
import AgentConversationTimeline from './AgentConversationTimeline.vue'

const props = defineProps<{
  question: string
  messages:
    | readonly ConversationMessage[]
    | DeepReadonly<ConversationMessage[]>
  latestResult: AgentRunResponse | DeepReadonly<AgentRunResponse> | null
  currentConversationId: string | null
  currentConversationTitle: string
  isRunning: boolean
  isLoadingHistory: boolean
  error: string
  notice: string
}>()

const emit = defineEmits<{
  'update:question': [value: string]
  send: []
}>()

const timelineViewport = ref<HTMLElement | null>(null)
const examples = [
  '电脑无法连接公司网络',
  '打印机无法正常打印',
  '查看刚才那个工单',
  '把刚才的工单改成无法连接 Wi-Fi',
]

function handleInput(event: Event) {
  emit('update:question', (event.target as HTMLTextAreaElement).value)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    submit()
  }
}

function submit() {
  if (!props.question.trim() || props.isRunning) {
    return
  }
  emit('send')
}

function useExample(message: string) {
  if (!props.isRunning) {
    emit('update:question', message)
  }
}

watch(
  () => [
    props.messages.length,
    props.messages.at(-1)?.content,
    props.latestResult,
  ],
  async () => {
    await nextTick()
    timelineViewport.value?.scrollTo({
      top: timelineViewport.value.scrollHeight,
      behavior: props.isRunning ? 'auto' : 'smooth',
    })
  },
  { flush: 'post' },
)
</script>

<template>
  <section class="assistant-panel">
    <header class="panel-heading">
      <div>
        <h2 data-testid="agent-conversation-title">
          {{ currentConversationTitle || '新对话' }}
        </h2>
        <p>
          <template v-if="currentConversationId">
            <span>可以继续追问或修改刚才的工单</span>
            <span
              class="visually-hidden"
              data-testid="agent-current-conversation-id"
            >{{ currentConversationId }}</span>
          </template>
          <template v-else>
            描述问题后，工单助手会帮你整理成工单
          </template>
        </p>
      </div>
      <ElTag
        round
        effect="plain"
        class="session-tag"
        :class="{ 'session-tag--new': !currentConversationId }"
      >
        {{ currentConversationId ? '可继续对话' : '新对话' }}
      </ElTag>
    </header>

    <div class="example-row">
      <button
        v-for="example in examples"
        :key="example"
        type="button"
        :disabled="isRunning"
        @click="useExample(example)"
      >
        {{ example }}
      </button>
    </div>

    <div ref="timelineViewport" class="result-viewport">
      <AgentConversationTimeline
        :messages="messages"
        :latest-result="latestResult"
        :is-loading="isLoadingHistory"
      />
    </div>

    <div v-if="error" class="panel-error" role="alert" data-testid="agent-error">
      {{ error }}
    </div>
    <div v-if="notice" class="panel-notice" data-testid="agent-notice">
      {{ notice }}
    </div>

    <div class="agent-composer">
      <textarea
        :value="question"
        rows="4"
        maxlength="4000"
        placeholder="例如：办公电脑无法连接公司 Wi-Fi，请帮我创建工单…"
        data-testid="agent-input"
        :disabled="isRunning || isLoadingHistory"
        @input="handleInput"
        @keydown="handleKeydown"
      />
      <div class="composer-footer">
        <span>Ctrl + Enter 快速发送</span>
        <ElButton
          type="primary"
          native-type="button"
          :loading="isRunning"
          :disabled="!question.trim() || isRunning || isLoadingHistory"
          data-testid="agent-run"
          @click="submit"
        >
          发送
        </ElButton>
      </div>
    </div>
  </section>
</template>

<style scoped>
.assistant-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  padding: 18px;
  background:
    radial-gradient(circle at 92% 2%, rgb(45 212 191 / 12%), transparent 25%),
    rgb(255 255 255 / 82%);
  border: 1px solid #dbe7e3;
  border-radius: 19px;
  box-shadow: 0 18px 48px rgb(20 60 55 / 7%);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.panel-heading h2 {
  max-width: 290px;
  margin: 0 0 4px;
  overflow: hidden;
  color: #173f3b;
  font-size: 19px;
  font-weight: 650;
  letter-spacing: -0.03em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-heading p {
  max-width: 300px;
  margin: 0;
  overflow: hidden;
  color: #849692;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-tag {
  height: 24px;
  color: #227368;
  background: #f0fcf8;
  border-color: #c8eae2;
  font-size: 10px;
}

.session-tag--new {
  color: #7d6a44;
  background: #fffaf0;
  border-color: #eadcbe;
}

.example-row {
  display: flex;
  gap: 5px;
  margin-top: 12px;
  overflow-x: auto;
  scrollbar-width: none;
}

.example-row button {
  flex: 0 0 auto;
  padding: 6px 9px;
  color: #5f7d78;
  background: #f7faf9;
  border: 1px solid #dfe9e6;
  border-radius: 999px;
  font-size: 10px;
  cursor: pointer;
}

.result-viewport {
  flex: 1;
  min-height: 0;
  margin-top: 11px;
  padding-right: 3px;
  overflow-y: auto;
  scrollbar-color: rgb(15 118 110 / 20%) transparent;
  scrollbar-width: thin;
}

.panel-error,
.panel-notice {
  margin-top: 7px;
  padding: 8px 10px;
  border-radius: 9px;
  font-size: 10px;
  line-height: 1.5;
}

.panel-error {
  color: #9a3f38;
  background: #fff4f1;
  border: 1px solid #f2d5ce;
}

.panel-notice {
  color: #28675e;
  background: #effaf6;
  border: 1px solid #d1ece4;
}

.agent-composer {
  flex: 0 0 auto;
  margin-top: 8px;
  padding: 9px;
  background: #fff;
  border: 1px solid #d7e4e1;
  border-radius: 13px;
  box-shadow: 0 8px 22px rgb(29 72 67 / 6%);
}

.agent-composer:focus-within {
  border-color: rgb(13 148 136 / 50%);
  box-shadow: 0 0 0 3px rgb(13 148 136 / 7%);
}

.agent-composer textarea {
  display: block;
  width: 100%;
  min-height: 62px;
  resize: none;
  color: #2e4e49;
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 13px;
  line-height: 1.65;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.composer-footer span {
  color: #98a6a2;
  font-size: 9px;
}

.composer-footer :deep(.el-button) {
  height: 32px;
  color: #fff;
  background: #0f766e;
  border-color: #0f766e;
  border-radius: 9px;
  font-size: 11px;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
