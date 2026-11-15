<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  action: 'request' | 'approve' | 'reject'
  draftTitle: string
  isSubmitting: boolean
}>()

const emit = defineEmits<{
  confirm: [note: string]
  cancel: []
}>()

const note = ref('')

const labels = {
  request: {
    title: '提交工单草稿审批',
    description: '提交后 LangGraph 会暂停，草稿将进入 pending_approval，审批完成前不能修改。',
    confirm: '确认提交审批',
  },
  approve: {
    title: '批准工单草稿',
    description: '批准是本地演示中的真实数据库写入，后端会恢复 Checkpoint 并更新最终状态。',
    confirm: '确认批准',
  },
  reject: {
    title: '拒绝工单草稿',
    description: '拒绝后草稿进入 rejected，不能再次提交同一审批流程。',
    confirm: '确认拒绝',
  },
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      note.value = ''
    }
  },
)

function confirm() {
  emit('confirm', note.value.trim())
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="dialog-backdrop"
      data-testid="approval-confirm-dialog"
      @click.self="emit('cancel')"
    >
      <section
        class="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-dialog-title"
      >
        <span class="dialog-kicker">LOCAL HUMAN REVIEW</span>
        <h2 id="approval-dialog-title">{{ labels[action].title }}</h2>
        <p class="draft-name">{{ draftTitle }}</p>
        <p class="dialog-copy">{{ labels[action].description }}</p>

        <label v-if="action !== 'request'" class="note-field">
          <span>审批备注（可选）</span>
          <textarea
            v-model="note"
            rows="3"
            maxlength="2000"
            placeholder="记录批准或拒绝原因…"
            data-testid="approval-note"
            :disabled="isSubmitting"
          />
        </label>

        <div class="dialog-actions">
          <button
            type="button"
            :disabled="isSubmitting"
            @click="emit('cancel')"
          >
            取消
          </button>
          <button
            type="button"
            class="confirm-button"
            :class="{ 'confirm-button--danger': action === 'reject' }"
            :disabled="isSubmitting"
            data-testid="approval-confirm-button"
            @click="confirm"
          >
            {{ isSubmitting ? '提交中…' : labels[action].confirm }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop {
  position: fixed;
  z-index: 1000;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgb(9 31 29 / 42%);
  backdrop-filter: blur(5px);
}

.confirm-dialog {
  width: min(430px, 100%);
  padding: 23px;
  color: #294944;
  background: #fff;
  border: 1px solid #d9e7e3;
  border-radius: 18px;
  box-shadow: 0 26px 80px rgb(10 45 41 / 24%);
}

.dialog-kicker {
  color: #78938e;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.17em;
}

.confirm-dialog h2 {
  margin: 5px 0 0;
  color: #173f3b;
  font-size: 20px;
}

.draft-name {
  margin: 13px 0 0;
  padding: 8px 10px;
  color: #315852;
  background: #f4f9f7;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 650;
}

.dialog-copy {
  margin: 10px 0 0;
  color: #788c87;
  font-size: 10px;
  line-height: 1.7;
}

.note-field {
  display: grid;
  gap: 5px;
  margin-top: 14px;
}

.note-field span {
  color: #6c8580;
  font-size: 9px;
}

.note-field textarea {
  width: 100%;
  padding: 9px 10px;
  resize: vertical;
  color: #355651;
  border: 1px solid #d8e4e1;
  border-radius: 9px;
  outline: 0;
  font-size: 11px;
}

.note-field textarea:focus {
  border-color: #60aa9f;
  box-shadow: 0 0 0 3px rgb(13 148 136 / 8%);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 17px;
}

.dialog-actions button {
  padding: 8px 13px;
  color: #617974;
  background: #fff;
  border: 1px solid #d8e3e0;
  border-radius: 9px;
  font-size: 10px;
  cursor: pointer;
}

.dialog-actions button:disabled {
  cursor: wait;
  opacity: 0.6;
}

.dialog-actions .confirm-button {
  color: #fff;
  background: #0f766e;
  border-color: #0f766e;
}

.dialog-actions .confirm-button--danger {
  background: #b5473f;
  border-color: #b5473f;
}
</style>
