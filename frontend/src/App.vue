<script setup lang="ts">
import {
  KeepAlive,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import { ElButton, ElTag } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'

import ChatComposer from './components/ChatComposer.vue'
import ChatMessageBubble from './components/ChatMessageBubble.vue'
import { useChat } from './composables/useChat'
import AgentView from './views/AgentView.vue'
import KnowledgeView from './views/KnowledgeView.vue'

const {
  messages,
  isGenerating,
  maxMessageLength,
  sendMessage,
  stopGeneration,
  clearConversation,
} = useChat()

const input = ref('')
const activeView = ref<'chat' | 'knowledge' | 'agent'>('chat')
const messageViewport = ref<HTMLElement | null>(null)
const composer = ref<InstanceType<typeof ChatComposer> | null>(null)
const actionError = ref('')
let scrollFrame = 0

const suggestions = [
  '如何评估一个 RAG 系统的检索质量？',
  '企业知识库 Agent 应该如何设计工具边界？',
  '帮我梳理一个 AI 应用开发实习项目亮点',
]

function scheduleScrollToBottom() {
  cancelAnimationFrame(scrollFrame)
  scrollFrame = requestAnimationFrame(() => {
    const viewport = messageViewport.value
    if (!viewport) {
      return
    }
    viewport.scrollTo({
      top: viewport.scrollHeight,
      behavior: isGenerating.value ? 'auto' : 'smooth',
    })
  })
}

async function handleSend() {
  const message = input.value.trim()
  if (!message || isGenerating.value) {
    return
  }

  actionError.value = ''
  input.value = ''
  await nextTick()
  try {
    await sendMessage(message)
  } catch (error) {
    actionError.value =
      error instanceof Error ? error.message : '发送失败，请稍后重试。'
  } finally {
    await nextTick()
    composer.value?.focus()
  }
}

function useSuggestion(text: string) {
  input.value = text
  composer.value?.focus()
}

function handleClear() {
  actionError.value = ''
  clearConversation()
  composer.value?.focus()
}

watch(
  () => [
    messages.value.length,
    messages.value.at(-1)?.content,
    messages.value.at(-1)?.status,
  ],
  scheduleScrollToBottom,
  { flush: 'post' },
)

onMounted(() => {
  composer.value?.focus()
})

onBeforeUnmount(() => {
  cancelAnimationFrame(scrollFrame)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <span />
          <span />
        </div>
        <div>
          <strong>OpsPilot</strong>
          <small>AI OPERATIONS COPILOT</small>
        </div>
      </div>

      <div class="sidebar-section">
        <p class="sidebar-label">工作台</p>
        <nav aria-label="主要导航">
          <button
            type="button"
            class="nav-item"
            :class="{ 'nav-item--active': activeView === 'chat' }"
            data-testid="nav-chat"
            @click="activeView = 'chat'"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M4 5.75A2.75 2.75 0 0 1 6.75 3h10.5A2.75 2.75 0 0 1 20 5.75v9.5A2.75 2.75 0 0 1 17.25 18H9.8l-4.2 3v-3.45A2.75 2.75 0 0 1 4 15.25v-9.5Zm4 2.5a1 1 0 0 0 0 2h8a1 1 0 1 0 0-2H8Zm0 4a1 1 0 1 0 0 2h5a1 1 0 1 0 0-2H8Z"
              />
            </svg>
            <span>智能问答</span>
            <span v-if="activeView === 'chat'" class="nav-pulse" />
          </button>
          <button
            type="button"
            class="nav-item"
            :class="{ 'nav-item--active': activeView === 'knowledge' }"
            data-testid="nav-knowledge"
            @click="activeView = 'knowledge'"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M5 3.75A1.75 1.75 0 0 1 6.75 2h10.5A1.75 1.75 0 0 1 19 3.75v16.5a1.75 1.75 0 0 1-1.75 1.75H6.75A1.75 1.75 0 0 1 5 20.25V3.75Zm3.2 2.3v2h7.6v-2H8.2Zm0 4v2h7.6v-2H8.2Zm0 4v2h5.2v-2H8.2Z"
              />
            </svg>
            <span>知识库问答</span>
            <span v-if="activeView === 'knowledge'" class="nav-pulse" />
          </button>
          <button
            type="button"
            class="nav-item"
            :class="{ 'nav-item--active': activeView === 'agent' }"
            data-testid="nav-agent"
            @click="activeView = 'agent'"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M7 3h10a2 2 0 0 1 2 2v3h1.25a.75.75 0 0 1 0 1.5H19v4h1.25a.75.75 0 0 1 0 1.5H19V19a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-3H3.75a.75.75 0 0 1 0-1.5H5v-4H3.75a.75.75 0 0 1 0-1.5H5V5a2 2 0 0 1 2-2Zm2 4a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1H9Zm1 3.25h4v1.5h-4v-1.5Zm0 3h2.75v1.5H10v-1.5Z"
              />
            </svg>
            <span>Agent 助手</span>
            <span v-if="activeView === 'agent'" class="nav-pulse" />
          </button>
        </nav>
      </div>

      <div class="sidebar-card">
        <div class="card-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path
              d="m12 2.5 2.2 5.45 5.8 2.3-5.8 2.3L12 18l-2.2-5.45-5.8-2.3 5.8-2.3L12 2.5Zm6.8 12.1 1.05 2.6 2.65 1.05-2.65 1.05-1.05 2.6-1.05-2.6-2.65-1.05 2.65-1.05 1.05-2.6Z"
            />
          </svg>
        </div>
        <p>
          {{
            activeView === 'chat'
              ? '面向企业知识场景的 AI 助手'
              : activeView === 'knowledge'
                ? '检索增强的企业知识工作台'
                : '从自然语言到工单审批的 Agent 工作台'
          }}
        </p>
        <span>
          {{
            activeView === 'chat'
              ? '支持 DeepSeek 实时流式问答'
              : activeView === 'knowledge'
                ? 'Hybrid 检索 · 引用校验 · 证据不足拒答'
                : 'Supervisor 路由 · Tool Calling · Human-in-the-loop'
          }}
        </span>
      </div>

      <div class="sidebar-spacer" />

      <div class="session-note">
        <span class="session-note__dot" />
        <div>
          <strong>
            {{
              activeView === 'chat'
                ? '当前为单轮问答'
                : activeView === 'knowledge'
                  ? '问答与索引状态仅保留在本页'
                  : '工单与审批使用真实本地持久化'
            }}
          </strong>
          <p>
            {{
              activeView === 'agent'
                ? '审批仅用于 localhost 本地演示'
                : '不提供服务端会话或索引状态持久化承诺'
            }}
          </p>
        </div>
      </div>

      <p class="version">OpsPilot · Phase 6 Preview</p>
    </aside>

    <main v-if="activeView === 'chat'" class="chat-panel">
      <header class="topbar">
        <div>
          <p class="eyebrow">AI ASSISTANT</p>
          <h1>智能问答</h1>
        </div>

        <div class="topbar-actions">
          <ElTag round effect="plain" class="stream-tag">
            <span class="live-dot" />
            流式响应
          </ElTag>
          <ElButton
            class="clear-button"
            text
            native-type="button"
            :disabled="messages.length === 0 && !actionError"
            @click="handleClear"
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path
                d="M7.2 2.75h5.6l.7 1.5h3.25v1.6H3.25v-1.6H6.5l.7-1.5ZM4.6 7h10.8l-.68 9.13A1.75 1.75 0 0 1 12.98 17.8H7.02a1.75 1.75 0 0 1-1.74-1.67L4.6 7Zm3.15 2.15a.75.75 0 0 0-.75.75v5a.75.75 0 0 0 1.5 0v-5a.75.75 0 0 0-.75-.75Zm4.5 0a.75.75 0 0 0-.75.75v5a.75.75 0 0 0 1.5 0v-5a.75.75 0 0 0-.75-.75Z"
              />
            </svg>
            清空对话
          </ElButton>
        </div>
      </header>

      <section
        ref="messageViewport"
        class="message-viewport"
        aria-live="polite"
      >
        <div class="conversation">
          <div v-if="messages.length === 0" class="welcome">
            <div class="welcome-orbit" aria-hidden="true">
              <div class="welcome-mark">
                <svg viewBox="0 0 32 32">
                  <path
                    d="m16 3 3.05 7.9L27 14l-7.95 3.1L16 25l-3.05-7.9L5 14l7.95-3.1L16 3Zm9.1 17.25 1.35 3.3 3.35 1.35-3.35 1.35-1.35 3.3-1.35-3.3-3.35-1.35 3.35-1.35 1.35-3.3Z"
                  />
                </svg>
              </div>
            </div>

            <p class="welcome-kicker">WELCOME TO OPSPILOT</p>
            <h2>让企业知识，<br />成为可对话的生产力。</h2>
            <p class="welcome-copy">
              输入问题，即可获得由 DeepSeek 实时生成的回答。
              当前阶段只把本条问题发送给服务端，不会声称拥有服务端会话记忆。
            </p>

            <div class="suggestion-grid">
              <button
                v-for="(suggestion, index) in suggestions"
                :key="suggestion"
                type="button"
                class="suggestion"
                @click="useSuggestion(suggestion)"
              >
                <span>0{{ index + 1 }}</span>
                <p>{{ suggestion }}</p>
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <path
                    d="m11.35 4.25 5.4 5.4a.5.5 0 0 1 0 .7l-5.4 5.4-1.05-1.06 3.57-3.57H3.5V9.88h10.37l-3.57-3.57 1.05-1.06Z"
                  />
                </svg>
              </button>
            </div>
          </div>

          <div v-else class="message-list">
            <ChatMessageBubble
              v-for="message in messages"
              :key="message.id"
              :message="message"
            />
          </div>
        </div>
      </section>

      <footer class="composer-region">
        <div v-if="actionError" class="action-error" role="alert">
          {{ actionError }}
        </div>
        <ChatComposer
          ref="composer"
          v-model="input"
          :is-generating="isGenerating"
          :max-length="maxMessageLength"
          @send="handleSend"
          @stop="stopGeneration"
        />
      </footer>
    </main>
    <KeepAlive>
      <AgentView v-if="activeView === 'agent'" />
      <KnowledgeView v-else-if="activeView === 'knowledge'" />
    </KeepAlive>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 286px minmax(0, 1fr);
  width: 100%;
  height: 100dvh;
  overflow: hidden;
}

.sidebar {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  padding: 27px 22px 20px;
  color: #dce8e6;
  background:
    radial-gradient(circle at 10% 5%, rgb(45 212 191 / 12%), transparent 32%),
    linear-gradient(165deg, #0d2424, #112d2c 52%, #0b2021);
  border-right: 1px solid rgb(255 255 255 / 6%);
}

.brand {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 2px 4px 28px;
}

.brand-mark {
  position: relative;
  display: grid;
  place-items: center;
  width: 37px;
  height: 37px;
  border: 1px solid rgb(94 234 212 / 32%);
  border-radius: 12px;
  background: rgb(45 212 191 / 9%);
  transform: rotate(8deg);
}

.brand-mark span {
  position: absolute;
  width: 15px;
  height: 3px;
  border-radius: 10px;
  background: #5eead4;
}

.brand-mark span:first-child {
  transform: rotate(90deg);
}

.brand strong {
  display: block;
  color: #f1fffc;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  font-size: 19px;
  letter-spacing: -0.02em;
}

.brand small {
  display: block;
  margin-top: 3px;
  color: #759b96;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.15em;
}

.sidebar-label {
  margin: 0 8px 9px;
  color: #6e928e;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 45px;
  padding: 0 12px;
  border-radius: 12px;
  width: 100%;
  color: #b8cbc7;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.nav-item--active {
  color: #f1fffc;
  background:
    linear-gradient(90deg, rgb(45 212 191 / 15%), transparent),
    rgb(255 255 255 / 5%);
  border: 1px solid rgb(94 234 212 / 10%);
}

.nav-item + .nav-item {
  margin-top: 6px;
}

.nav-item svg {
  width: 19px;
  height: 19px;
  fill: #8bd9cf;
}

.nav-pulse {
  width: 6px;
  height: 6px;
  margin-left: auto;
  border-radius: 50%;
  background: #5eead4;
  box-shadow: 0 0 0 4px rgb(94 234 212 / 8%);
}

.sidebar-card {
  margin-top: 24px;
  padding: 16px;
  border: 1px solid rgb(255 255 255 / 7%);
  border-radius: 16px;
  background:
    linear-gradient(145deg, rgb(255 255 255 / 5%), rgb(255 255 255 / 2%));
}

.card-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  color: #5eead4;
  border-radius: 10px;
  background: rgb(45 212 191 / 10%);
}

.card-icon svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

.sidebar-card p {
  margin: 13px 0 5px;
  color: #d9e9e6;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}

.sidebar-card span {
  color: #74948f;
  font-size: 10px;
  line-height: 1.55;
}

.sidebar-spacer {
  flex: 1;
}

.session-note {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 12px;
  border-top: 1px solid rgb(255 255 255 / 6%);
}

.session-note__dot {
  flex: 0 0 6px;
  width: 6px;
  height: 6px;
  margin-top: 5px;
  border-radius: 50%;
  background: #f59e0b;
}

.session-note strong {
  display: block;
  color: #c6d8d5;
  font-size: 11px;
  font-weight: 600;
}

.session-note p {
  margin: 4px 0 0;
  color: #65837e;
  font-size: 9px;
  line-height: 1.5;
}

.version {
  margin: 8px 0 0;
  color: #4f6d69;
  font-size: 9px;
  text-align: center;
}

.chat-panel {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  background:
    radial-gradient(circle at 86% 8%, rgb(94 234 212 / 12%), transparent 25%),
    radial-gradient(circle at 12% 92%, rgb(147 197 253 / 10%), transparent 27%),
    #f6f8f7;
}

.chat-panel::before {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgb(15 118 110 / 2.8%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(15 118 110 / 2.8%) 1px, transparent 1px);
  background-size: 34px 34px;
  mask-image: linear-gradient(to bottom, black, transparent 70%);
  content: "";
  pointer-events: none;
}

.topbar {
  position: relative;
  z-index: 1;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  min-height: 82px;
  padding: 17px 34px 14px;
  border-bottom: 1px solid rgb(208 219 222 / 62%);
  background: rgb(246 248 247 / 74%);
  backdrop-filter: blur(16px);
}

.eyebrow {
  margin: 0 0 3px;
  color: #7a938f;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.17em;
}

.topbar h1 {
  margin: 0;
  color: #163a38;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.035em;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stream-tag {
  height: 30px;
  color: #25766e;
  background: rgb(240 253 250 / 74%);
  border-color: rgb(153 226 214 / 64%);
  font-size: 11px;
}

.live-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 50%;
  background: #14b8a6;
  box-shadow: 0 0 0 3px rgb(20 184 166 / 12%);
}

.clear-button {
  height: 32px;
  color: #728783;
  font-size: 12px;
}

.clear-button:hover {
  color: #294f4b;
  background: rgb(15 118 110 / 6%);
}

.clear-button svg {
  width: 16px;
  height: 16px;
  margin-right: 5px;
  fill: currentColor;
}

.message-viewport {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-color: rgb(15 118 110 / 20%) transparent;
  scrollbar-width: thin;
}

.conversation {
  width: min(920px, calc(100% - 56px));
  min-height: 100%;
  margin: 0 auto;
  padding: 30px 0 22px;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 14px 2px 20px;
}

.welcome {
  display: flex;
  align-items: center;
  min-height: 100%;
  flex-direction: column;
  justify-content: center;
  padding: clamp(26px, 6vh, 70px) 0 26px;
  text-align: center;
  animation: welcome-in 500ms ease both;
}

.welcome-orbit {
  position: relative;
  display: grid;
  place-items: center;
  width: 88px;
  height: 88px;
  margin-bottom: 19px;
  border: 1px solid rgb(15 118 110 / 12%);
  border-radius: 50%;
}

.welcome-orbit::before,
.welcome-orbit::after {
  position: absolute;
  border-radius: 50%;
  content: "";
}

.welcome-orbit::before {
  inset: 9px;
  border: 1px dashed rgb(15 118 110 / 17%);
  animation: orbit 18s linear infinite;
}

.welcome-orbit::after {
  top: 5px;
  right: 15px;
  width: 7px;
  height: 7px;
  background: #2dd4bf;
  box-shadow: 0 0 0 5px rgb(45 212 191 / 9%);
}

.welcome-mark {
  display: grid;
  place-items: center;
  width: 51px;
  height: 51px;
  color: #f0fdfa;
  border-radius: 17px;
  background: linear-gradient(145deg, #0f766e, #134e4a);
  box-shadow: 0 14px 30px rgb(15 118 110 / 20%);
  transform: rotate(-5deg);
}

.welcome-mark svg {
  width: 29px;
  height: 29px;
  fill: currentColor;
  transform: rotate(5deg);
}

.welcome-kicker {
  margin: 0 0 10px;
  color: #75938e;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.18em;
}

.welcome h2 {
  margin: 0;
  color: #173c39;
  font-family: "Avenir Next", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  font-size: clamp(27px, 3.1vw, 38px);
  font-weight: 620;
  line-height: 1.28;
  letter-spacing: -0.035em;
}

.welcome-copy {
  max-width: 570px;
  margin: 15px auto 0;
  color: #728681;
  font-size: 13px;
  line-height: 1.8;
}

.suggestion-grid {
  display: grid;
  width: min(720px, 100%);
  margin-top: 27px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.suggestion {
  display: flex;
  min-height: 104px;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  padding: 14px 15px;
  color: #294f4b;
  text-align: left;
  background: rgb(255 255 255 / 68%);
  border: 1px solid rgb(204 219 219 / 72%);
  border-radius: 15px;
  cursor: pointer;
  transition:
    transform 170ms ease,
    border-color 170ms ease,
    box-shadow 170ms ease,
    background 170ms ease;
}

.suggestion:hover {
  background: rgb(255 255 255 / 92%);
  border-color: rgb(45 165 151 / 34%);
  box-shadow: 0 12px 26px rgb(32 78 73 / 8%);
  transform: translateY(-2px);
}

.suggestion span {
  color: #92aaa5;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.suggestion p {
  margin: 9px 0;
  font-size: 12px;
  font-weight: 550;
  line-height: 1.55;
}

.suggestion svg {
  align-self: flex-end;
  width: 15px;
  height: 15px;
  fill: #70a39c;
}

.composer-region {
  position: relative;
  z-index: 2;
  flex: 0 0 auto;
  padding: 12px 28px 14px;
  background: linear-gradient(to top, #f6f8f7 65%, rgb(246 248 247 / 0%));
}

.action-error {
  width: min(920px, 100%);
  margin: 0 auto 8px;
  padding: 9px 13px;
  color: #9f3a38;
  background: #fff4f2;
  border: 1px solid #ffd8d1;
  border-radius: 11px;
  font-size: 12px;
}

@keyframes orbit {
  to {
    transform: rotate(360deg);
  }
}

@keyframes welcome-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 980px) {
  .app-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .sidebar {
    display: flex;
    align-items: center;
    min-height: 62px;
    flex-direction: row;
    padding: 8px 14px;
    border-right: 0;
    border-bottom: 1px solid rgb(255 255 255 / 7%);
  }

  .brand {
    padding: 0;
  }

  .brand-mark {
    width: 32px;
    height: 32px;
  }

  .brand small,
  .sidebar-label,
  .sidebar-card,
  .sidebar-spacer,
  .session-note,
  .version {
    display: none;
  }

  .sidebar-section {
    margin-left: auto;
  }

  .nav-item {
    display: inline-flex;
    width: auto;
    min-height: 38px;
    margin: 0;
    padding: 0 10px;
    font-size: 11px;
  }

  .nav-item + .nav-item {
    margin-top: 0;
    margin-left: 5px;
  }

  .sidebar-section nav {
    display: flex;
    align-items: center;
  }

  .nav-item svg {
    width: 16px;
    height: 16px;
  }

  .nav-pulse {
    display: none;
  }

  .conversation {
    width: min(920px, calc(100% - 38px));
  }

  .topbar {
    padding-inline: 22px;
  }
}

@media (max-width: 720px) {
  .suggestion-grid {
    grid-template-columns: 1fr;
  }

  .suggestion {
    min-height: 77px;
  }

  .suggestion p {
    margin-block: 6px;
  }

  .welcome {
    padding-top: 22px;
  }

  .welcome-orbit {
    width: 72px;
    height: 72px;
    margin-bottom: 14px;
  }
}

@media (max-width: 560px) {
  .brand strong {
    font-size: 15px;
  }

  .brand-mark {
    display: none;
  }

  .topbar {
    min-height: 70px;
    padding: 12px 15px;
  }

  .topbar h1 {
    font-size: 21px;
  }

  .stream-tag {
    display: none;
  }

  .conversation {
    width: calc(100% - 24px);
    padding-top: 16px;
  }

  .message-list {
    gap: 18px;
  }

  .welcome h2 {
    font-size: 26px;
  }

  .welcome-copy {
    font-size: 12px;
  }

  .composer-region {
    padding: 9px 11px 10px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .welcome,
  .welcome-orbit::before {
    animation: none;
  }
}
</style>

