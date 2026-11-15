<script setup lang="ts">
import {
  computed,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { ElButton, ElTag } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'

import { useTicketWorkspace } from '../../composables/useTicketWorkspace'
import type {
  ApprovalDecision,
  TicketDraft,
  TicketDraftStatus,
} from '../../types/agent'
import ApprovalConfirmDialog from './ApprovalConfirmDialog.vue'

const {
  drafts,
  selectedDraft,
  approval,
  selectedThreadId,
  isBusy,
  canEdit,
  isLoading,
  isLoadingDetail,
  isSaving,
  isRequestingApproval,
  isDeciding,
  error,
  notice,
  refreshDrafts,
  selectDraft,
  focusAgentDraft,
  updateSelected,
  submitSelectedForApproval,
  refreshSelectedApproval,
  decideSelected,
  clearMessages,
} = useTicketWorkspace()

const isEditing = ref(false)
const confirmAction = ref<'request' | 'approve' | 'reject' | null>(null)
const editValues = reactive({
  title: '',
  description: '',
  device_or_system: '',
})

const statusMeta: Record<
  TicketDraftStatus,
  { label: string; type: 'info' | 'warning' | 'success' | 'danger' }
> = {
  draft: { label: '草稿', type: 'info' },
  pending_approval: { label: '等待审批', type: 'warning' },
  approved: { label: '已批准', type: 'success' },
  rejected: { label: '已拒绝', type: 'danger' },
}

const confirmSubmitting = computed(() => {
  if (confirmAction.value === 'request') {
    return isRequestingApproval.value
  }
  return confirmAction.value !== null && isDeciding.value
})

const editInvalid = computed(
  () => !editValues.title.trim()
    || !editValues.description.trim()
    || !editValues.device_or_system.trim(),
)

function resetEditValues() {
  const draft = selectedDraft.value
  editValues.title = draft?.title ?? ''
  editValues.description = draft?.description ?? ''
  editValues.device_or_system = draft?.device_or_system ?? ''
}

watch(
  () => [
    selectedDraft.value?.id,
    selectedDraft.value?.version,
    selectedDraft.value?.status,
  ],
  () => {
    isEditing.value = false
    resetEditValues()
  },
)

onMounted(async () => {
  await refreshDrafts()
  const first = drafts.value[0]
  if (first) {
    await selectDraft(first.id)
  }
})

async function focusDraft(draft: TicketDraft) {
  clearMessages()
  await focusAgentDraft(draft)
  resetEditValues()
}

defineExpose({ focusDraft })

function startEditing() {
  if (!canEdit.value) {
    return
  }
  clearMessages()
  resetEditValues()
  isEditing.value = true
}

async function saveDraft() {
  if (editInvalid.value || !canEdit.value) {
    return
  }
  const updated = await updateSelected({
    title: editValues.title.trim(),
    description: editValues.description.trim(),
    device_or_system: editValues.device_or_system.trim(),
  })
  if (updated) {
    isEditing.value = false
  }
}

function openConfirmation(action: 'request' | 'approve' | 'reject') {
  clearMessages()
  confirmAction.value = action
}

async function handleConfirmed(note: string) {
  const action = confirmAction.value
  if (!action) {
    return
  }
  const result = action === 'request'
    ? await submitSelectedForApproval()
    : await decideSelected(action as ApprovalDecision, note)
  if (result) {
    confirmAction.value = null
  }
}

function formatDate(value: string | null): string {
  if (!value) {
    return '—'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <section class="ticket-panel">
    <header class="ticket-heading">
      <div>
        <span class="ticket-kicker">PERSISTED TICKET WORKSPACE</span>
        <h2>工单草稿与审批</h2>
        <p>所有状态以 SQLite 和 LangGraph Checkpoint 的真实响应为准。</p>
      </div>
      <ElTag round effect="plain" class="local-tag">LOCAL DEMO</ElTag>
    </header>

    <div class="workspace-grid">
      <aside class="draft-queue">
        <header>
          <div>
            <strong>草稿列表</strong>
            <span>{{ drafts.length }} 条记录</span>
          </div>
          <ElButton
            circle
            text
            :loading="isLoading"
            aria-label="刷新工单草稿"
            data-testid="ticket-refresh"
            @click="refreshDrafts"
          >
            ↻
          </ElButton>
        </header>

        <div class="draft-list">
          <div v-if="isLoading && drafts.length === 0" class="queue-empty">
            正在读取草稿…
          </div>
          <div v-else-if="drafts.length === 0" class="queue-empty">
            还没有草稿。先在左侧让 Agent 创建一份工单。
          </div>
          <button
            v-for="draft in drafts"
            :key="draft.id"
            type="button"
            class="draft-row"
            :class="{ active: selectedDraft?.id === draft.id }"
            data-testid="ticket-draft-row"
            :data-draft-id="draft.id"
            :disabled="isBusy && selectedDraft?.id !== draft.id"
            @click="selectDraft(draft.id)"
          >
            <span class="row-accent" />
            <span class="row-main">
              <strong>{{ draft.title }}</strong>
              <span>
                v{{ draft.version }} · {{ formatDate(draft.updated_at) }}
              </span>
            </span>
            <ElTag
              size="small"
              effect="plain"
              :type="statusMeta[draft.status].type"
            >
              {{ statusMeta[draft.status].label }}
            </ElTag>
          </button>
        </div>
      </aside>

      <section class="draft-detail">
        <div v-if="isLoadingDetail" class="detail-empty">
          正在读取真实草稿…
        </div>
        <div v-else-if="!selectedDraft" class="detail-empty">
          <div class="empty-mark">OP</div>
          <strong>选择一份工单草稿</strong>
          <p>可查看详情、编辑 draft 状态草稿，并提交人工审批。</p>
        </div>

        <template v-else>
          <header class="detail-header">
            <div>
              <span class="detail-kicker">TICKET DRAFT</span>
              <h3>{{ selectedDraft.title }}</h3>
              <p><code>{{ selectedDraft.id }}</code></p>
            </div>
            <ElTag
              effect="plain"
              :type="statusMeta[selectedDraft.status].type"
              data-testid="ticket-status"
            >
              {{ statusMeta[selectedDraft.status].label }}
            </ElTag>
          </header>

          <div class="draft-meta">
            <span>内容版本 v{{ selectedDraft.version }}</span>
            <span>创建 {{ formatDate(selectedDraft.created_at) }}</span>
            <span>更新 {{ formatDate(selectedDraft.updated_at) }}</span>
          </div>

          <form
            v-if="isEditing"
            class="edit-form"
            @submit.prevent="saveDraft"
          >
            <label>
              <span>标题</span>
              <input
                v-model="editValues.title"
                maxlength="200"
                data-testid="ticket-edit-title"
              >
            </label>
            <label>
              <span>设备或系统</span>
              <input
                v-model="editValues.device_or_system"
                maxlength="200"
                data-testid="ticket-edit-device"
              >
            </label>
            <label>
              <span>问题描述</span>
              <textarea
                v-model="editValues.description"
                rows="6"
                maxlength="4000"
                data-testid="ticket-edit-description"
              />
            </label>
            <div class="form-actions">
              <button
                type="button"
                :disabled="isSaving"
                @click="isEditing = false"
              >
                取消
              </button>
              <button
                type="submit"
                class="primary-button"
                :disabled="editInvalid || isSaving"
                data-testid="ticket-save"
              >
                {{ isSaving ? '保存中…' : '保存修改' }}
              </button>
            </div>
          </form>

          <template v-else>
            <dl class="draft-fields">
              <div>
                <dt>设备或系统</dt>
                <dd>{{ selectedDraft.device_or_system }}</dd>
              </div>
              <div>
                <dt>问题描述</dt>
                <dd>{{ selectedDraft.description }}</dd>
              </div>
            </dl>

            <div v-if="selectedDraft.status === 'draft'" class="draft-actions">
              <div>
                <strong>准备提交人工审批</strong>
                <p>审批暂停后，草稿修改会被后端拒绝，直到人工决策完成。</p>
              </div>
              <div class="action-buttons">
                <button
                  type="button"
                  :disabled="!canEdit"
                  data-testid="ticket-edit-button"
                  @click="startEditing"
                >
                  编辑草稿
                </button>
                <button
                  type="button"
                  class="primary-button"
                  :disabled="isBusy"
                  data-testid="ticket-request-approval"
                  @click="openConfirmation('request')"
                >
                  提交审批
                </button>
              </div>
            </div>

            <section
              v-else
              class="approval-section"
              data-testid="ticket-approval-section"
            >
              <div class="approval-heading">
                <div>
                  <span class="detail-kicker">HUMAN-IN-THE-LOOP</span>
                  <h4>审批工作流</h4>
                </div>
                <button
                  v-if="selectedThreadId"
                  type="button"
                  :disabled="isBusy"
                  data-testid="ticket-refresh-approval"
                  @click="refreshSelectedApproval"
                >
                  刷新真实状态
                </button>
              </div>

              <div
                v-if="!selectedThreadId"
                class="missing-thread"
                data-testid="ticket-missing-thread"
              >
                该草稿处于 {{ statusMeta[selectedDraft.status].label }}，
                但当前浏览器没有保存对应 thread_id。后端只提供按 thread_id
                查询审批，因此本页不能安全恢复这个流程。
              </div>

              <template v-else>
                <dl class="approval-grid">
                  <div>
                    <dt>草稿状态</dt>
                    <dd>{{ statusMeta[selectedDraft.status].label }}</dd>
                  </div>
                  <div>
                    <dt>等待人工决定</dt>
                    <dd>{{ approval?.waiting_for_decision ? '是' : '否' }}</dd>
                  </div>
                  <div>
                    <dt>审批时间</dt>
                    <dd>{{ formatDate(approval?.approval.requested_at ?? null) }}</dd>
                  </div>
                  <div>
                    <dt>决策时间</dt>
                    <dd>{{ formatDate(approval?.approval.decided_at ?? null) }}</dd>
                  </div>
                </dl>

                <div class="thread-id">
                  <span>thread_id</span>
                  <code>{{ selectedThreadId }}</code>
                </div>

                <div v-if="approval?.checkpoint_next.length" class="checkpoint-line">
                  Checkpoint 下一节点：
                  <code>{{ approval.checkpoint_next.join(' → ') }}</code>
                </div>

                <div
                  v-if="approval?.approval.note"
                  class="decision-note"
                >
                  <span>人工备注</span>
                  <p>{{ approval.approval.note }}</p>
                </div>

                <div
                  v-if="selectedDraft.status === 'pending_approval'"
                  class="decision-actions"
                >
                  <p>
                    当前没有正式登录鉴权，这是 localhost 本地演示。
                    操作会真实恢复 LangGraph Checkpoint。
                  </p>
                  <div>
                    <button
                      type="button"
                      class="reject-button"
                      :disabled="isBusy || !approval?.waiting_for_decision"
                      data-testid="ticket-reject"
                      @click="openConfirmation('reject')"
                    >
                      拒绝
                    </button>
                    <button
                      type="button"
                      class="primary-button"
                      :disabled="isBusy || !approval?.waiting_for_decision"
                      data-testid="ticket-approve"
                      @click="openConfirmation('approve')"
                    >
                      批准
                    </button>
                  </div>
                </div>
              </template>
            </section>
          </template>

          <div v-if="notice" class="workspace-message workspace-message--notice" data-testid="ticket-notice">
            {{ notice }}
          </div>
          <div v-if="error" class="workspace-message workspace-message--error" role="alert" data-testid="ticket-error">
            {{ error }}
          </div>

          <p class="workspace-note">
            本地演示模式：审批接口没有正式审批人身份、角色或租户校验。
            thread_id 仅保存在当前浏览器本地，用于查询已创建的真实流程。
          </p>
        </template>
      </section>
    </div>

    <ApprovalConfirmDialog
      :open="confirmAction !== null"
      :action="confirmAction ?? 'request'"
      :draft-title="selectedDraft?.title ?? ''"
      :is-submitting="confirmSubmitting"
      @confirm="handleConfirmed"
      @cancel="confirmAction = null"
    />
  </section>
</template>

<style scoped>
.ticket-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  padding: 20px;
  background: rgb(249 252 251 / 84%);
  border: 1px solid #dbe7e3;
  border-radius: 19px;
  box-shadow: 0 18px 48px rgb(20 60 55 / 7%);
}

.ticket-heading {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.ticket-kicker,
.detail-kicker {
  color: #748e89;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.15em;
}

.ticket-heading h2 {
  margin: 4px 0 3px;
  color: #173f3b;
  font-size: 21px;
  font-weight: 650;
}

.ticket-heading p {
  margin: 0;
  color: #859793;
  font-size: 9px;
}

.local-tag {
  height: 25px;
  color: #8a6427;
  background: #fff8e8;
  border-color: #ead9b6;
  font-size: 8px;
}

.workspace-grid {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: minmax(190px, 0.72fr) minmax(330px, 1.45fr);
  gap: 12px;
  margin-top: 15px;
}

.draft-queue,
.draft-detail {
  min-height: 0;
  overflow: hidden;
  background: #fff;
  border: 1px solid #e0e9e6;
  border-radius: 14px;
}

.draft-queue {
  display: flex;
  flex-direction: column;
}

.draft-queue > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 12px 9px;
  border-bottom: 1px solid #edf2f0;
}

.draft-queue > header strong,
.draft-queue > header span {
  display: block;
}

.draft-queue > header strong {
  color: #3c5d58;
  font-size: 11px;
}

.draft-queue > header span {
  margin-top: 2px;
  color: #96a5a2;
  font-size: 8px;
}

.draft-list {
  flex: 1;
  min-height: 0;
  padding: 5px;
  overflow-y: auto;
  scrollbar-color: rgb(15 118 110 / 20%) transparent;
  scrollbar-width: thin;
}

.queue-empty {
  display: grid;
  min-height: 130px;
  place-items: center;
  padding: 20px;
  color: #93a39f;
  font-size: 9px;
  line-height: 1.6;
  text-align: center;
}

.draft-row {
  position: relative;
  display: grid;
  width: 100%;
  grid-template-columns: 3px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 9px 8px;
  color: #496661;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  cursor: pointer;
}

.draft-row + .draft-row {
  margin-top: 2px;
}

.draft-row.active {
  background: #f0faf7;
  border-color: #d3ebe4;
}

.draft-row:disabled {
  cursor: wait;
  opacity: 0.6;
}

.row-accent {
  width: 3px;
  height: 25px;
  background: #d4e5e1;
  border-radius: 3px;
}

.draft-row.active .row-accent {
  background: #2aa896;
}

.row-main {
  min-width: 0;
}

.row-main strong,
.row-main > span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-main strong {
  color: #365852;
  font-size: 10px;
}

.row-main > span {
  margin-top: 3px;
  color: #93a29f;
  font-size: 7px;
}

.draft-row :deep(.el-tag) {
  height: 18px;
  font-size: 7px;
}

.draft-detail {
  padding: 16px;
  overflow-y: auto;
  scrollbar-color: rgb(15 118 110 / 20%) transparent;
  scrollbar-width: thin;
}

.detail-empty {
  display: flex;
  min-height: 100%;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  padding: 25px;
  color: #8d9f9b;
  font-size: 9px;
  text-align: center;
}

.empty-mark {
  display: grid;
  width: 42px;
  height: 42px;
  margin-bottom: 10px;
  place-items: center;
  color: #358c80;
  background: #edf8f5;
  border-radius: 13px;
  font-size: 10px;
  font-weight: 800;
}

.detail-empty strong {
  color: #4a6963;
  font-size: 12px;
}

.detail-empty p {
  margin: 5px 0 0;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.detail-header h3 {
  margin: 4px 0 4px;
  color: #193f3a;
  font-size: 17px;
}

.detail-header p {
  margin: 0;
}

.detail-header code {
  color: #96a5a2;
  font-size: 8px;
}

.detail-header :deep(.el-tag) {
  height: 22px;
  font-size: 8px;
}

.draft-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.draft-meta span {
  padding: 4px 7px;
  color: #7c918c;
  background: #f5f9f8;
  border-radius: 6px;
  font-size: 8px;
}

.draft-fields,
.approval-grid {
  display: grid;
  gap: 10px;
  margin: 15px 0 0;
}

.draft-fields > div {
  padding: 10px 11px;
  background: #fafcfb;
  border: 1px solid #edf2f0;
  border-radius: 9px;
}

.draft-fields dt,
.approval-grid dt {
  color: #849692;
  font-size: 8px;
}

.draft-fields dd {
  margin: 5px 0 0;
  color: #395b55;
  font-size: 11px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.draft-actions {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
  margin-top: 15px;
  padding-top: 13px;
  border-top: 1px solid #edf2f0;
}

.draft-actions strong {
  color: #42645e;
  font-size: 11px;
}

.draft-actions p {
  max-width: 350px;
  margin: 4px 0 0;
  color: #8a9b97;
  font-size: 8px;
  line-height: 1.55;
}

.action-buttons,
.form-actions,
.decision-actions > div {
  display: flex;
  flex: 0 0 auto;
  gap: 7px;
}

.action-buttons button,
.form-actions button,
.decision-actions button,
.approval-heading button {
  padding: 7px 10px;
  color: #54716c;
  background: #fff;
  border: 1px solid #d8e4e1;
  border-radius: 8px;
  font-size: 9px;
  cursor: pointer;
}

.action-buttons button:disabled,
.form-actions button:disabled,
.decision-actions button:disabled,
.approval-heading button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.action-buttons .primary-button,
.form-actions .primary-button,
.decision-actions .primary-button {
  color: #fff;
  background: #0f766e;
  border-color: #0f766e;
}

.decision-actions .reject-button {
  color: #a3433c;
  border-color: #e7cfcb;
}

.edit-form {
  display: grid;
  gap: 10px;
  margin-top: 15px;
}

.edit-form label {
  display: grid;
  gap: 4px;
}

.edit-form label span {
  color: #738b86;
  font-size: 8px;
}

.edit-form input,
.edit-form textarea {
  width: 100%;
  padding: 8px 9px;
  color: #385852;
  background: #fff;
  border: 1px solid #d9e5e2;
  border-radius: 8px;
  outline: 0;
  font-size: 10px;
}

.edit-form textarea {
  resize: vertical;
  line-height: 1.6;
}

.edit-form input:focus,
.edit-form textarea:focus {
  border-color: #63a99f;
  box-shadow: 0 0 0 3px rgb(13 148 136 / 7%);
}

.form-actions {
  justify-content: flex-end;
}

.approval-section {
  margin-top: 15px;
  padding: 13px;
  background:
    linear-gradient(145deg, rgb(248 251 250 / 92%), rgb(241 249 246 / 82%));
  border: 1px solid #dce9e5;
  border-radius: 12px;
}

.approval-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.approval-heading h4 {
  margin: 4px 0 0;
  color: #315650;
  font-size: 13px;
}

.approval-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 11px;
}

.approval-grid > div {
  padding: 8px;
  background: rgb(255 255 255 / 72%);
  border: 1px solid #e7efed;
  border-radius: 8px;
}

.approval-grid dd {
  margin: 4px 0 0;
  color: #496962;
  font-size: 9px;
}

.thread-id,
.checkpoint-line,
.decision-note,
.missing-thread {
  margin-top: 10px;
  padding: 8px 9px;
  color: #718a84;
  background: #fff;
  border: 1px solid #e6eeec;
  border-radius: 8px;
  font-size: 8px;
  line-height: 1.55;
}

.thread-id {
  display: grid;
  gap: 3px;
}

.thread-id code,
.checkpoint-line code {
  color: #3d665f;
  overflow-wrap: anywhere;
}

.decision-note span {
  font-weight: 700;
}

.decision-note p {
  margin: 4px 0 0;
  color: #486660;
}

.missing-thread {
  color: #966a25;
  background: #fffaf0;
  border-color: #ead9b8;
}

.decision-actions {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-top: 11px;
}

.decision-actions p {
  max-width: 390px;
  margin: 0;
  color: #8a9b97;
  font-size: 8px;
  line-height: 1.5;
}

.workspace-message {
  margin-top: 10px;
  padding: 8px 9px;
  border-radius: 8px;
  font-size: 9px;
  line-height: 1.55;
}

.workspace-message--notice {
  color: #28675e;
  background: #effaf6;
  border: 1px solid #d1ece4;
}

.workspace-message--error {
  color: #9b4039;
  background: #fff4f1;
  border: 1px solid #f1d3cc;
}

.workspace-note {
  margin: 11px 0 0;
  padding-top: 9px;
  color: #97a6a2;
  border-top: 1px solid #edf2f0;
  font-size: 8px;
  line-height: 1.55;
}

@media (max-width: 1180px) {
  .workspace-grid {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(160px, 0.55fr) minmax(360px, 1.45fr);
  }
}

@media (max-width: 720px) {
  .ticket-panel {
    min-height: 760px;
    padding: 16px;
  }

  .workspace-grid {
    grid-template-rows: minmax(190px, auto) minmax(420px, auto);
  }

  .draft-actions,
  .decision-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .action-buttons,
  .decision-actions > div {
    justify-content: flex-end;
  }
}
</style>
