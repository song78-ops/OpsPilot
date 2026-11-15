<script setup lang="ts">
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'

import type { ConversationSummary } from '../../types/agent'

defineProps<{
  conversations: readonly ConversationSummary[]
  currentConversationId: string | null
  isLoading: boolean
  isRunning: boolean
}>()

const emit = defineEmits<{
  newConversation: []
  selectConversation: [conversationId: string]
  refresh: []
}>()

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <aside class="session-rail">
    <header class="rail-heading">
      <div>
        <span>AGENT SESSIONS</span>
        <h2>会话</h2>
      </div>
      <ElButton
        circle
        text
        :loading="isLoading"
        :disabled="isRunning"
        aria-label="刷新会话列表"
        data-testid="agent-conversation-refresh"
        @click="emit('refresh')"
      >
        ↻
      </ElButton>
    </header>

    <ElButton
      class="new-session-button"
      native-type="button"
      :disabled="isRunning || isLoading"
      data-testid="agent-new-conversation"
      @click="emit('newConversation')"
    >
      <span>＋</span>
      新建会话
    </ElButton>

    <div class="session-list" data-testid="agent-conversation-list">
      <div v-if="isLoading && conversations.length === 0" class="rail-empty">
        正在读取会话…
      </div>
      <div v-else-if="conversations.length === 0" class="rail-empty">
        还没有历史会话。首次发送消息后由后端创建。
      </div>

      <button
        v-for="conversation in conversations"
        :key="conversation.conversation_id"
        type="button"
        class="session-item"
        :class="{
          active: currentConversationId === conversation.conversation_id,
        }"
        :disabled="isRunning"
        :data-conversation-id="conversation.conversation_id"
        data-testid="agent-conversation-item"
        @click="emit('selectConversation', conversation.conversation_id)"
      >
        <span class="session-dot" />
        <span class="session-copy">
          <strong>{{ conversation.title }}</strong>
          <small>{{ formatDate(conversation.updated_at) }}</small>
          <code>{{ conversation.conversation_id }}</code>
        </span>
      </button>
    </div>

    <p class="rail-note">
      消息正文只从服务端加载。本地仅缓存最近使用的 conversation_id。
    </p>
  </aside>
</template>

<style scoped>
.session-rail {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  padding: 16px 13px;
  background:
    linear-gradient(165deg, rgb(13 48 45 / 98%), rgb(14 59 55 / 96%));
  border: 1px solid rgb(255 255 255 / 7%);
  border-radius: 19px;
  box-shadow: 0 18px 48px rgb(20 60 55 / 10%);
}

.rail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.rail-heading span {
  color: #79a59d;
  font-size: 7px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.rail-heading h2 {
  margin: 4px 0 0;
  color: #ecfdf9;
  font-size: 17px;
}

.rail-heading :deep(.el-button) {
  color: #9ed0c8;
}

.new-session-button {
  width: 100%;
  height: 34px;
  margin-top: 13px;
  color: #dffcf6;
  background: rgb(45 212 191 / 12%);
  border-color: rgb(94 234 212 / 18%);
  border-radius: 9px;
  font-size: 9px;
}

.new-session-button:hover {
  color: #fff;
  background: rgb(45 212 191 / 18%);
  border-color: rgb(94 234 212 / 28%);
}

.new-session-button span {
  margin-right: 5px;
  font-size: 14px;
}

.session-list {
  flex: 1;
  min-height: 0;
  margin-top: 9px;
  padding-right: 2px;
  overflow-y: auto;
  scrollbar-color: rgb(94 234 212 / 20%) transparent;
  scrollbar-width: thin;
}

.rail-empty {
  display: grid;
  min-height: 150px;
  place-items: center;
  padding: 16px;
  color: #7faaa2;
  font-size: 8px;
  line-height: 1.65;
  text-align: center;
}

.session-item {
  display: flex;
  width: 100%;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 8px;
  color: #cce6e1;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  cursor: pointer;
}

.session-item + .session-item {
  margin-top: 3px;
}

.session-item:hover {
  background: rgb(255 255 255 / 4%);
}

.session-item.active {
  background: rgb(45 212 191 / 11%);
  border-color: rgb(94 234 212 / 14%);
}

.session-item:disabled {
  cursor: wait;
  opacity: 0.65;
}

.session-dot {
  flex: 0 0 5px;
  width: 5px;
  height: 5px;
  margin-top: 7px;
  background: #507c76;
  border-radius: 50%;
}

.session-item.active .session-dot {
  background: #5eead4;
  box-shadow: 0 0 0 3px rgb(94 234 212 / 9%);
}

.session-copy {
  display: block;
  min-width: 0;
}

.session-copy strong,
.session-copy small,
.session-copy code {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-copy strong {
  color: #dff4f0;
  font-size: 9px;
}

.session-copy small {
  margin-top: 3px;
  color: #739c95;
  font-size: 7px;
}

.session-copy code {
  margin-top: 3px;
  color: #5f8780;
  font-size: 6px;
}

.rail-note {
  margin: 9px 2px 0;
  padding-top: 9px;
  color: #668e87;
  border-top: 1px solid rgb(255 255 255 / 6%);
  font-size: 7px;
  line-height: 1.55;
}

@media (max-width: 900px) {
  .session-rail {
    min-height: 190px;
  }

  .session-list {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .session-item {
    flex: 0 0 170px;
  }

  .rail-note {
    display: none;
  }
}
</style>
