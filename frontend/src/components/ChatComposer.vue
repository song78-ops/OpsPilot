<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'

const model = defineModel<string>({ required: true })

const props = defineProps<{
  isGenerating: boolean
  maxLength: number
}>()

const emit = defineEmits<{
  send: []
  stop: []
}>()

const textarea = ref<HTMLTextAreaElement | null>(null)

function resizeTextarea() {
  const element = textarea.value
  if (!element) {
    return
  }
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 168)}px`
}

async function focus() {
  await nextTick()
  textarea.value?.focus()
}

function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  model.value = target.value
  resizeTextarea()
}

function handleKeydown(event: KeyboardEvent) {
  if (
    event.key === 'Enter' &&
    !event.shiftKey &&
    !event.isComposing
  ) {
    event.preventDefault()
    if (!props.isGenerating && model.value.trim()) {
      emit('send')
    }
  }
}

watch(model, resizeTextarea)
onMounted(resizeTextarea)

defineExpose({ focus })
</script>

<template>
  <div class="composer-wrap">
    <div class="composer" :class="{ 'composer--busy': isGenerating }">
      <textarea
        ref="textarea"
        :value="model"
        :maxlength="maxLength"
        rows="1"
        aria-label="输入问题"
        data-testid="chat-input"
        placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
        @input="handleInput"
        @keydown="handleKeydown"
      />

      <div class="composer-footer">
        <span class="composer-hint">
          <span class="hint-dot" />
          <template v-if="isGenerating">正在组织回答，可随时停止</template>
          <template v-else>Enter 发送 · Shift + Enter 换行</template>
        </span>

        <div class="composer-actions">
          <span
            v-if="model.length > 9000"
            class="character-count"
          >
            {{ model.length }} / {{ maxLength }}
          </span>

          <ElButton
            v-if="isGenerating"
            class="stop-button"
            native-type="button"
            @click="emit('stop')"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <rect x="4" y="4" width="8" height="8" rx="1.5" />
            </svg>
            停止生成
          </ElButton>

          <ElButton
            v-else
            class="send-button"
            native-type="button"
            :disabled="!model.trim()"
            data-testid="chat-send"
            @click="emit('send')"
          >
            发送
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path
                d="M3.1 10.2 16.6 4l-4.2 12.4-2.35-4.85-6.95-1.35Zm6.25.95 1.4 2.88 2.2-6.5-3.6 3.62Z"
              />
            </svg>
          </ElButton>
        </div>
      </div>
    </div>

    <p class="privacy-note">
      OpsPilot 只把当前问题发送给服务端模型，API Key 不会进入浏览器。
    </p>
  </div>
</template>

<style scoped>
.composer-wrap {
  width: min(920px, 100%);
  margin: 0 auto;
}

.composer {
  position: relative;
  padding: 14px 14px 10px;
  background: rgb(255 255 255 / 92%);
  border: 1px solid rgb(201 216 224 / 90%);
  border-radius: 19px;
  box-shadow:
    0 18px 50px rgb(22 58 63 / 11%),
    0 2px 8px rgb(22 58 63 / 4%);
  backdrop-filter: blur(18px);
  transition:
    border-color 160ms ease,
    box-shadow 160ms ease;
}

.composer:focus-within {
  border-color: rgb(13 148 136 / 55%);
  box-shadow:
    0 18px 50px rgb(22 58 63 / 12%),
    0 0 0 4px rgb(13 148 136 / 8%);
}

.composer--busy {
  border-color: rgb(13 148 136 / 30%);
}

textarea {
  display: block;
  width: 100%;
  min-height: 44px;
  max-height: 168px;
  padding: 4px 5px 8px;
  resize: none;
  color: var(--ink);
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 15px;
  line-height: 1.7;
}

textarea::placeholder {
  color: #9aa8b5;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.composer-hint {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  color: #91a0ad;
  font-size: 11px;
  white-space: nowrap;
}

.hint-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2dd4bf;
  box-shadow: 0 0 0 3px rgb(45 212 191 / 13%);
}

.composer-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
}

.character-count {
  color: #9aa8b5;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.send-button,
.stop-button {
  height: 36px;
  padding: 0 14px;
  border-radius: 11px;
  font-weight: 650;
}

.send-button {
  color: #f8fffe;
  background: linear-gradient(135deg, #0f766e, #0d9488);
  border-color: transparent;
  box-shadow: 0 7px 18px rgb(13 148 136 / 20%);
}

.send-button:hover,
.send-button:focus {
  color: #fff;
  background: linear-gradient(135deg, #115e59, #0f766e);
  border-color: transparent;
}

.send-button:disabled {
  color: #9aa8b5;
  background: #eef2f4;
  box-shadow: none;
}

.send-button svg {
  width: 17px;
  height: 17px;
  fill: currentColor;
}

.stop-button {
  color: #9f3a38;
  background: #fff5f3;
  border-color: #f7d5d0;
}

.stop-button:hover,
.stop-button:focus {
  color: #842d2b;
  background: #ffebe7;
  border-color: #efbcb5;
}

.stop-button svg {
  width: 15px;
  height: 15px;
  margin-right: 5px;
  fill: currentColor;
}

.privacy-note {
  margin: 9px 0 0;
  color: #95a3af;
  font-size: 10px;
  text-align: center;
}

@media (max-width: 640px) {
  .composer {
    padding: 11px 11px 9px;
    border-radius: 16px;
  }

  .composer-hint {
    white-space: normal;
  }

  .composer-hint .hint-dot {
    display: none;
  }

  .privacy-note {
    display: none;
  }
}
</style>

