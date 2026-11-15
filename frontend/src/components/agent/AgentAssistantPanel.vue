<script setup lang="ts">
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'

import { useAgentAssistant } from '../../composables/useAgentAssistant'
import type { TicketDraft } from '../../types/agent'
import AgentResultCard from './AgentResultCard.vue'

const emit = defineEmits<{
  draftReady: [draft: TicketDraft]
}>()

const {
  question,
  isRunning,
  error,
  result,
  run,
  clear,
} = useAgentAssistant()

const examples = [
  'Redis 缓存击穿应该怎么解决？',
  '帮我创建电脑无法联网的维修工单。',
  '你好，介绍一下你自己。',
  '帮我处理一下这个问题。',
]

async function submit() {
  const response = await run()
  if (response?.ticket_draft) {
    emit('draftReady', response.ticket_draft)
  }
}

function useExample(message: string) {
  question.value = message
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    void submit()
  }
}
</script>

<template>
  <section class="assistant-panel">
    <header class="panel-heading">
      <div>
        <span class="panel-kicker">LANGGRAPH SUPERVISOR</span>
        <h2>Agent 智能助手</h2>
        <p>自动识别知识问答、普通聊天和工单请求。</p>
      </div>
      <ElButton
        v-if="result"
        text
        :disabled="isRunning"
        @click="clear"
      >
        清空结果
      </ElButton>
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

    <div class="result-viewport">
      <AgentResultCard
        v-if="result"
        :result="result"
        @open-draft="emit('draftReady', result.ticket_draft!)"
      />
      <div v-else class="assistant-welcome">
        <div class="welcome-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32">
            <path
              d="M8 5h12l5 5v17H8V5Zm11 2v5h5l-5-5ZM11 15h10v2H11v-2Zm0 5h10v2H11v-2Z"
            />
          </svg>
        </div>
        <strong>用自然语言发起一次完整业务流程</strong>
        <p>
          工单信息会通过后端原生 Tool Calling 保存；知识问题会进入带证据校验的
          RAG 流程。这里不展示未经后端确认的成功状态。
        </p>
      </div>
    </div>

    <div v-if="error" class="panel-error" role="alert" data-testid="agent-error">
      {{ error }}
    </div>

    <div class="agent-composer">
      <textarea
        v-model="question"
        rows="4"
        maxlength="4000"
        placeholder="例如：帮我创建一个电脑无法连接公司网络的维修工单…"
        data-testid="agent-input"
        :disabled="isRunning"
        @keydown="handleKeydown"
      />
      <div class="composer-footer">
        <span>Ctrl + Enter 提交 · 本阶段页面暂未接入会话历史</span>
        <ElButton
          type="primary"
          native-type="button"
          :loading="isRunning"
          :disabled="!question.trim() || isRunning"
          data-testid="agent-run"
          @click="submit"
        >
          运行 Agent
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
  padding: 20px;
  background:
    radial-gradient(circle at 92% 2%, rgb(45 212 191 / 12%), transparent 25%),
    rgb(255 255 255 / 78%);
  border: 1px solid #dbe7e3;
  border-radius: 19px;
  box-shadow: 0 18px 48px rgb(20 60 55 / 7%);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-kicker {
  color: #73928c;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.16em;
}

.panel-heading h2 {
  margin: 4px 0 3px;
  color: #173f3b;
  font-size: 21px;
  font-weight: 650;
  letter-spacing: -0.03em;
}

.panel-heading p {
  margin: 0;
  color: #849692;
  font-size: 9px;
}

.example-row {
  display: flex;
  gap: 5px;
  margin-top: 14px;
  overflow-x: auto;
  scrollbar-width: none;
}

.example-row button {
  flex: 0 0 auto;
  padding: 5px 8px;
  color: #5f7d78;
  background: #f7faf9;
  border: 1px solid #dfe9e6;
  border-radius: 999px;
  font-size: 8px;
  cursor: pointer;
}

.result-viewport {
  flex: 1;
  min-height: 0;
  margin-top: 13px;
  padding-right: 3px;
  overflow-y: auto;
  scrollbar-color: rgb(15 118 110 / 20%) transparent;
  scrollbar-width: thin;
}

.assistant-welcome {
  display: flex;
  min-height: 100%;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  padding: 22px 12px;
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

.assistant-welcome strong {
  margin-top: 13px;
  color: #31534f;
  font-size: 14px;
}

.assistant-welcome p {
  max-width: 360px;
  margin: 7px 0 0;
  color: #899b97;
  font-size: 10px;
  line-height: 1.75;
}

.panel-error {
  margin-top: 8px;
  padding: 8px 10px;
  color: #9a3f38;
  background: #fff4f1;
  border: 1px solid #f2d5ce;
  border-radius: 9px;
  font-size: 9px;
}

.agent-composer {
  flex: 0 0 auto;
  margin-top: 10px;
  padding: 10px;
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
  min-height: 70px;
  resize: none;
  color: #2e4e49;
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 12px;
  line-height: 1.7;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.composer-footer span {
  color: #98a6a2;
  font-size: 8px;
}

.composer-footer :deep(.el-button) {
  height: 30px;
  color: #fff;
  background: #0f766e;
  border-color: #0f766e;
  border-radius: 9px;
  font-size: 10px;
}
</style>
