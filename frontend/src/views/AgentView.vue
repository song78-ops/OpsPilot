<script setup lang="ts">
import { ref } from 'vue'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'

import AgentAssistantPanel from '../components/agent/AgentAssistantPanel.vue'
import TicketWorkspace from '../components/agent/TicketWorkspace.vue'
import type { TicketDraft } from '../types/agent'

const workspace = ref<InstanceType<typeof TicketWorkspace> | null>(null)

async function openDraft(draft: TicketDraft) {
  await workspace.value?.focusDraft(draft)
}
</script>

<template>
  <main class="agent-page">
    <header class="agent-header">
      <div>
        <p class="eyebrow">AGENT OPERATIONS WORKSPACE</p>
        <h1>Agent 智能助手</h1>
        <p class="agent-subtitle">
          从自然语言请求到工单草稿、人工审批和最终状态确认。
        </p>
      </div>
      <div class="header-badges">
        <ElTag round effect="plain" class="header-tag">
          <span class="ready-dot" />
          LangGraph
        </ElTag>
        <ElTag round effect="plain" class="header-tag header-tag--warning">
          本机人工审批
        </ElTag>
      </div>
    </header>

    <div class="agent-layout">
      <AgentAssistantPanel @draft-ready="openDraft" />
      <TicketWorkspace ref="workspace" />
    </div>

    <p class="page-note">
      当前没有正式登录、审批人身份或多租户权限控制。审批仅用于 localhost
      本地开发演示，所有状态均来自真实后端响应。
    </p>
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

.eyebrow {
  margin: 0 0 3px;
  color: #74908b;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.18em;
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

.header-badges {
  display: flex;
  align-items: center;
  gap: 7px;
}

.header-tag {
  height: 27px;
  color: #217268;
  background: rgb(240 253 250 / 82%);
  border-color: #bfe8df;
  font-size: 9px;
}

.header-tag--warning {
  color: #886127;
  background: #fff9e9;
  border-color: #edddbb;
}

.ready-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 4px;
  border-radius: 50%;
  background: #14b8a6;
}

.agent-layout {
  position: relative;
  z-index: 1;
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: minmax(360px, 0.88fr) minmax(560px, 1.55fr);
  gap: 13px;
}

.page-note {
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  margin: 9px 3px 0;
  color: #91a19e;
  font-size: 8px;
  text-align: center;
}

@media (max-width: 1220px) {
  .agent-page {
    padding: 16px;
    overflow-y: auto;
  }

  .agent-layout {
    flex: none;
    grid-template-columns: 1fr;
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
