<script setup lang="ts">
import { onMounted, ref } from 'vue'

import AgentAssistantPanel from '../components/agent/AgentAssistantPanel.vue'
import AgentSessionRail from '../components/agent/AgentSessionRail.vue'
import TicketWorkspace from '../components/agent/TicketWorkspace.vue'
import { useAgentAssistant } from '../composables/useAgentAssistant'
import type { TicketDraft } from '../types/agent'

const workspace = ref<InstanceType<typeof TicketWorkspace> | null>(null)
const {
  question,
  conversations,
  messages,
  currentConversationId,
  currentConversationTitle,
  latestResult,
  isRunning,
  isLoadingConversations,
  isLoadingHistory,
  isBusy,
  error,
  notice,
  restore,
  refresh,
  selectConversation,
  startNewConversation,
  send,
} = useAgentAssistant()

async function openDraft(draft: TicketDraft) {
  await workspace.value?.focusDraft(draft)
}

async function submitMessage() {
  const response = await send()
  if (response?.ticket_draft) {
    await openDraft(response.ticket_draft)
  }
}

function updateQuestion(value: string) {
  question.value = value
}

async function chooseConversation(conversationId: string) {
  await selectConversation(conversationId)
}

onMounted(() => {
  void restore()
})
</script>

<template>
  <main class="agent-page">
    <header class="agent-header">
      <div>
        <h1>工单助手</h1>
        <p class="agent-subtitle">
          描述遇到的问题，创建工单并跟进审批进度。
        </p>
      </div>
    </header>

    <div class="agent-layout">
      <AgentSessionRail
        :conversations="conversations"
        :current-conversation-id="currentConversationId"
        :is-loading="isLoadingConversations"
        :is-running="isBusy"
        @new-conversation="startNewConversation"
        @select-conversation="chooseConversation"
        @refresh="refresh"
      />
      <AgentAssistantPanel
        :question="question"
        :messages="messages"
        :latest-result="latestResult"
        :current-conversation-id="currentConversationId"
        :current-conversation-title="currentConversationTitle"
        :is-running="isRunning"
        :is-loading-history="isLoadingHistory"
        :error="error"
        :notice="notice"
        @update:question="updateQuestion"
        @send="submitMessage"
      />
      <TicketWorkspace ref="workspace" class="ticket-workspace" />
    </div>

  </main>
</template>

<style scoped>
.agent-page {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  padding: 20px 24px 18px;
  overflow: hidden;
  background:
    radial-gradient(circle at 97% 0%, rgb(45 212 191 / 11%), transparent 24%),
    radial-gradient(circle at 2% 95%, rgb(147 197 253 / 9%), transparent 21%),
    #f3f8f6;
}

.agent-page::before {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgb(15 118 110 / 2.4%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(15 118 110 / 2.4%) 1px, transparent 1px);
  background-size: 36px 36px;
  mask-image: linear-gradient(to bottom, black, transparent 68%);
  content: "";
  pointer-events: none;
}

.agent-header {
  position: relative;
  z-index: 1;
  display: flex;
  flex: 0 0 auto;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 14px;
}

.agent-header h1 {
  margin: 0;
  color: #153c38;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  font-size: 27px;
  font-weight: 650;
  letter-spacing: -0.04em;
}

.agent-subtitle {
  margin: 5px 0 0;
  color: #7c918c;
  font-size: 10px;
}

.agent-layout {
  position: relative;
  z-index: 1;
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns:
    minmax(190px, 0.42fr)
    minmax(330px, 0.82fr)
    minmax(500px, 1.55fr);
  gap: 13px;
}

@media (max-width: 1320px) {
  .agent-page {
    padding: 16px;
    overflow-y: auto;
  }

  .agent-layout {
    flex: none;
    grid-template-columns: minmax(190px, 0.45fr) minmax(0, 1fr);
  }

  .ticket-workspace {
    min-height: 680px;
    grid-column: 1 / -1;
  }
}

@media (max-width: 900px) {
  .agent-layout {
    grid-template-columns: 1fr;
  }

  .ticket-workspace {
    grid-column: auto;
  }
}

@media (max-width: 640px) {
  .agent-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .agent-subtitle {
    max-width: 320px;
    line-height: 1.55;
  }
}
</style>
