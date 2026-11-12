<script setup lang="ts">
import { computed } from 'vue'

import type { ChatMessage } from '../types/chat'

const props = defineProps<{
  message: ChatMessage
}>()

const isUser = computed(() => props.message.role === 'user')

const statusLabel = computed(() => {
  if (props.message.status === 'stopped') {
    return '已停止生成'
  }
  if (props.message.status === 'error') {
    return '回答失败'
  }
  return ''
})
</script>

<template>
  <article
    class="message-row"
    :class="{ 'message-row--user': isUser }"
    :aria-label="isUser ? '你的消息' : 'OpsPilot 的回答'"
  >
    <div v-if="!isUser" class="avatar avatar--assistant" aria-hidden="true">
      <svg viewBox="0 0 24 24" role="presentation">
        <path
          d="M12 3.25 13.9 8l4.85 1.9-4.85 1.9L12 16.55 10.1 11.8 5.25 9.9 10.1 8 12 3.25Zm6.15 11.1.92 2.28 2.43.97-2.43.97-.92 2.28-.92-2.28-2.43-.97 2.43-.97.92-2.28Z"
        />
      </svg>
    </div>

    <div class="message-stack">
      <div v-if="!isUser" class="message-author">OpsPilot</div>
      <div class="message-bubble">
        <div
          v-if="message.content"
          class="message-content"
        >{{ message.content }}</div>
        <div
          v-else-if="message.status === 'streaming'"
          class="thinking"
          aria-label="正在生成回答"
        >
          <span />
          <span />
          <span />
        </div>
        <div
          v-else-if="message.status === 'stopped'"
          class="empty-state"
        >
          生成已停止
        </div>
        <span
          v-if="message.status === 'streaming' && message.content"
          class="stream-caret"
          aria-hidden="true"
        />
      </div>

      <div
        v-if="message.error"
        class="message-error"
        role="alert"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path
            d="M10 2.5a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15Zm0 3.2c.46 0 .83.37.83.83v4.22a.83.83 0 1 1-1.66 0V6.53c0-.46.37-.83.83-.83Zm0 8.6a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"
          />
        </svg>
        {{ message.error }}
      </div>

      <div
        v-if="!isUser && (message.usage || statusLabel)"
        class="message-meta"
      >
        <span v-if="statusLabel">{{ statusLabel }}</span>
        <span v-if="message.usage">
          输入 {{ message.usage.prompt_tokens }} · 输出
          {{ message.usage.completion_tokens }} tokens
        </span>
      </div>
    </div>

    <div v-if="isUser" class="avatar avatar--user" aria-hidden="true">
      你
    </div>
  </article>
</template>

<style scoped>
.message-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
}

.message-row--user {
  justify-content: flex-end;
}

.message-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  max-width: min(78%, 760px);
}

.message-row--user .message-stack {
  align-items: flex-end;
}

.message-author {
  margin: 0 0 7px 4px;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.avatar {
  display: grid;
  flex: 0 0 36px;
  place-items: center;
  width: 36px;
  height: 36px;
  margin-top: 22px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 700;
}

.avatar--assistant {
  color: #ecfdf5;
  background:
    radial-gradient(circle at 28% 20%, #2dd4bf 0, transparent 35%),
    linear-gradient(145deg, #0f766e, #134e4a);
  box-shadow: 0 8px 20px rgb(15 118 110 / 22%);
}

.avatar--assistant svg {
  width: 20px;
  height: 20px;
  fill: currentColor;
}

.avatar--user {
  margin-top: 0;
  color: #475569;
  background: #e8edf3;
  border: 1px solid #dce3ec;
}

.message-row--user .message-stack {
  margin-top: 0;
}

.message-bubble {
  position: relative;
  padding: 14px 17px;
  border-radius: 8px 20px 20px;
  color: var(--ink);
  background: rgb(255 255 255 / 88%);
  border: 1px solid rgb(214 224 232 / 86%);
  box-shadow: 0 10px 35px rgb(31 55 68 / 7%);
}

.message-row--user .message-bubble {
  color: #f8fffe;
  background: linear-gradient(145deg, #0f766e, #115e59);
  border: 0;
  border-radius: 20px 8px 20px 20px;
  box-shadow: 0 12px 30px rgb(15 118 110 / 20%);
}

.message-content {
  font-size: 15px;
  line-height: 1.78;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.stream-caret {
  display: inline-block;
  width: 2px;
  height: 1.05em;
  margin-left: 3px;
  vertical-align: -2px;
  background: var(--accent);
  animation: blink 0.9s steps(2, start) infinite;
}

.thinking {
  display: flex;
  align-items: center;
  gap: 5px;
  min-height: 22px;
  padding: 1px 2px;
}

.thinking span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #60a5fa;
  animation: thinking 1.2s ease-in-out infinite;
}

.thinking span:nth-child(2) {
  animation-delay: 0.15s;
}

.thinking span:nth-child(3) {
  animation-delay: 0.3s;
}

.empty-state {
  color: var(--ink-muted);
  font-size: 14px;
  font-style: italic;
}

.message-error {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 9px;
  padding: 9px 12px;
  color: #a83838;
  background: #fff4f2;
  border: 1px solid #ffd8d1;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.55;
}

.message-error svg {
  flex: 0 0 16px;
  width: 16px;
  margin-top: 2px;
  fill: currentColor;
}

.message-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 7px 4px 0;
  color: #94a3b8;
  font-size: 11px;
}

.message-meta span + span::before {
  content: '·';
  margin-right: 14px;
  color: #cbd5e1;
}

@keyframes thinking {
  0%,
  70%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  35% {
    opacity: 1;
    transform: translateY(-4px);
  }
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

@media (max-width: 640px) {
  .message-stack {
    max-width: calc(100% - 48px);
  }

  .avatar {
    flex-basis: 32px;
    width: 32px;
    height: 32px;
  }

  .message-bubble {
    padding: 12px 14px;
  }

  .message-content {
    font-size: 14px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .thinking span,
  .stream-caret {
    animation: none;
  }
}
</style>

