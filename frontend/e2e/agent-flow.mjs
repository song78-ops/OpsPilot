import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { chromium } from 'playwright-core'

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const phase = process.argv[2] || process.env.E2E_PHASE || 'prepare'
const screenshotDir = path.resolve('e2e/artifacts')
const statePath = path.join(screenshotDir, 'agent-flow-state.json')
const storageKey = 'opspilot.approval.threads.v1'
const consoleErrors = []

await mkdir(screenshotDir, { recursive: true })

async function launchPage(browser) {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1050 },
    locale: 'zh-CN',
  })
  const page = await context.newPage()
  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text())
    }
  })
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message)
  })
  return { context, page }
}

async function openAgent(page) {
  await page.goto(baseUrl, { waitUntil: 'networkidle' })
  await page.getByTestId('nav-agent').click()
  await page.getByRole('heading', {
    name: 'Agent 智能助手',
    level: 1,
  }).waitFor()
}

async function runTicketAgent(page, prompt) {
  await page.getByTestId('agent-input').fill(prompt)
  await page.getByTestId('agent-run').click()
  await page.getByTestId('agent-draft-card').waitFor({ timeout: 180_000 })
  const draftId = (
    await page.getByTestId('agent-draft-card').locator('code').first().innerText()
  ).trim()
  assert.match(draftId, /^[0-9a-f]{32}$/)
  await page.getByTestId('agent-open-draft').click()
  await page.locator(`[data-testid="ticket-draft-row"][data-draft-id="${draftId}"]`).waitFor()
  return draftId
}

async function openDraft(page, draftId) {
  const row = page.locator(
    `[data-testid="ticket-draft-row"][data-draft-id="${draftId}"]`,
  )
  await row.waitFor({ timeout: 60_000 })
  await row.click()
}

async function confirmApprovalAction(page, note = '') {
  await page.getByTestId('approval-confirm-dialog').waitFor()
  if (note) {
    await page.getByTestId('approval-note').fill(note)
  }
  await page.getByTestId('approval-confirm-button').click()
  await page.getByTestId('approval-confirm-dialog').waitFor({ state: 'detached' })
}

async function fetchApproval(page, threadId) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/agent/approvals/${id}`)
    if (!response.ok) {
      throw new Error(`Approval API failed with ${response.status}`)
    }
    return response.json()
  }, threadId)
}

async function smokeExistingPages(page) {
  await page.getByTestId('nav-chat').click()
  await page.getByTestId('chat-input').fill('只回复 OK')
  await page.getByTestId('chat-send').click()
  await page.waitForFunction(
    () => document.querySelectorAll('.message-row').length >= 2,
    undefined,
    { timeout: 180_000 },
  )
  const chatAnswer = await page.locator('.message-content').last().innerText()
  assert.ok(chatAnswer.trim().length > 0)

  await page.getByTestId('nav-knowledge').click()
  await page.getByRole('heading', { name: '企业知识库', level: 1 }).waitFor()
  await page.getByTestId('document-row').first().waitFor({ timeout: 60_000 })
  await page.getByTestId('rag-question-input').fill(
    '缓存击穿应该怎么处理？',
  )
  await page.getByTestId('rag-ask-button').click()
  await page.getByTestId('rag-result').last().waitFor({ timeout: 180_000 })
  assert.equal(await page.getByTestId('rag-error').count(), 0)
  await page.screenshot({
    path: path.join(screenshotDir, 'existing-pages-after-agent-flow.png'),
    fullPage: true,
  })
}

async function verifyAgentIntent(page, prompt, heading) {
  await page.getByTestId('agent-input').fill(prompt)
  await page.getByTestId('agent-run').click()
  await page.getByTestId('agent-result')
    .getByRole('heading', { name: heading, level: 3 })
    .waitFor({ timeout: 180_000 })
  await page.getByTestId('agent-run').waitFor({ state: 'visible' })
  assert.equal(await page.getByTestId('agent-error').count(), 0)
}

const browser = await chromium.launch({
  executablePath: edgePath,
  headless: true,
})

try {
  if (phase === 'prepare') {
    const { context, page } = await launchPage(browser)
    await openAgent(page)

    const marker = Date.now()
    const title = `E2E 网络故障 ${marker}`
    const draftId = await runTicketAgent(
      page,
      `帮我创建一个办公电脑无法联网的工单草稿，设备是 E2E 测试笔记本，`
      + `描述为无法连接公司内网，标题使用“${title}”。`,
    )

    await page.getByTestId('ticket-edit-button').click()
    await page.getByTestId('ticket-edit-description').fill(
      `浏览器 E2E 更新：办公电脑无法连接公司内网，时间标记 ${marker}。`,
    )
    await page.getByTestId('ticket-save').click()
    await page.getByTestId('ticket-notice').waitFor()
    await page.getByTestId('ticket-notice').getByText(/后端确认/).waitFor()

    await page.getByTestId('ticket-request-approval').click()
    await confirmApprovalAction(page)
    await page.getByTestId('ticket-status').getByText('等待审批').waitFor()
    const threadId = (
      await page.locator('.thread-id code').innerText()
    ).trim()
    assert.match(threadId, /^[0-9a-f]{32}$/)

    const persisted = await fetchApproval(page, threadId)
    assert.equal(persisted.draft.id, draftId)
    assert.equal(persisted.draft.status, 'pending_approval')
    assert.equal(persisted.waiting_for_decision, true)

    await writeFile(
      statePath,
      JSON.stringify({ draftId, threadId, title, marker }, null, 2),
      'utf8',
    )
    await page.screenshot({
      path: path.join(screenshotDir, 'agent-pending-before-restart.png'),
      fullPage: true,
    })
    await context.close()
    console.log('agent-flow: prepare passed')
    console.log(`state: ${statePath}`)
  } else if (phase === 'resume') {
    const state = JSON.parse(await readFile(statePath, 'utf8'))
    const { context, page } = await launchPage(browser)
    await page.goto(baseUrl, { waitUntil: 'networkidle' })
    await page.evaluate(
      ({ key, draftId, threadId }) => {
        localStorage.setItem(key, JSON.stringify({ [draftId]: threadId }))
      },
      {
        key: storageKey,
        draftId: state.draftId,
        threadId: state.threadId,
      },
    )
    await page.reload({ waitUntil: 'networkidle' })
    await page.getByTestId('nav-agent').click()
    await page.getByRole('heading', {
      name: 'Agent 智能助手',
      level: 1,
    }).waitFor()
    await openDraft(page, state.draftId)

    await page.getByTestId('ticket-status').getByText('等待审批').waitFor()
    await page.getByTestId('ticket-refresh-approval').click()
    await page.getByText('Checkpoint 下一节点：').waitFor()
    const recovered = await fetchApproval(page, state.threadId)
    assert.equal(recovered.waiting_for_decision, true)
    assert.deepEqual(recovered.checkpoint_next, ['await_decision'])
    await page.screenshot({
      path: path.join(screenshotDir, 'agent-recovered-after-restart.png'),
      fullPage: true,
    })

    await page.getByTestId('ticket-approve').click()
    await confirmApprovalAction(page, '浏览器 E2E 批准')
    await page.getByTestId('ticket-status').getByText('已批准').waitFor()
    await page.getByTestId('ticket-notice').getByText(/重新确认/).waitFor()

    const approved = await fetchApproval(page, state.threadId)
    assert.equal(approved.approval.status, 'approved')
    assert.equal(approved.draft.status, 'approved')
    assert.equal(approved.waiting_for_decision, false)
    await page.screenshot({
      path: path.join(screenshotDir, 'agent-approved.png'),
      fullPage: true,
    })

    const secondDraftId = await runTicketAgent(
      page,
      `再创建一个测试工单草稿，标题使用“E2E 拒绝流程 ${state.marker}”，`
      + '设备是会议室投影仪，描述为会议开始前没有画面。',
    )
    await page.getByTestId('ticket-request-approval').click()
    await confirmApprovalAction(page)
    await page.getByTestId('ticket-status').getByText('等待审批').waitFor()
    const secondThreadId = (
      await page.locator('.thread-id code').innerText()
    ).trim()

    await page.getByTestId('ticket-reject').click()
    await confirmApprovalAction(page, '浏览器 E2E 拒绝')
    await page.getByTestId('ticket-status').getByText('已拒绝').waitFor()
    await page.getByTestId('ticket-notice').getByText(/重新确认/).waitFor()
    const rejected = await fetchApproval(page, secondThreadId)
    assert.equal(rejected.approval.status, 'rejected')
    assert.equal(rejected.draft.status, 'rejected')
    assert.equal(rejected.waiting_for_decision, false)

    await page.screenshot({
      path: path.join(screenshotDir, 'agent-rejected.png'),
      fullPage: true,
    })

    await smokeExistingPages(page)

    await writeFile(
      path.join(screenshotDir, 'agent-flow-result.json'),
      JSON.stringify(
        {
          approved_draft_id: state.draftId,
          approved_thread_id: state.threadId,
          rejected_draft_id: secondDraftId,
          rejected_thread_id: secondThreadId,
        },
        null,
        2,
      ),
      'utf8',
    )
    await context.close()
    assert.deepEqual(consoleErrors, [])
    console.log('agent-flow: resume passed')
    console.log(`approved-draft: ${state.draftId}`)
    console.log(`rejected-draft: ${secondDraftId}`)
  } else if (phase === 'smoke') {
    const { context, page } = await launchPage(browser)
    await page.goto(baseUrl, { waitUntil: 'networkidle' })
    await smokeExistingPages(page)
    await context.close()
    assert.deepEqual(consoleErrors, [])
    console.log('agent-flow: existing pages smoke passed')
  } else if (phase === 'intents') {
    const { context, page } = await launchPage(browser)
    await openAgent(page)

    await verifyAgentIntent(page, '你好，介绍一下你自己。', '普通聊天')
    assert.ok(
      (await page.getByTestId('agent-answer').innerText()).trim().length > 0,
    )

    await verifyAgentIntent(page, 'Redis 缓存击穿应该怎么解决？', '知识库问答')
    await page.getByText('知识库引用').waitFor({ timeout: 180_000 })

    await verifyAgentIntent(page, '帮我处理一下这个问题。', '需要补充')

    await verifyAgentIntent(
      page,
      '帮我创建一个测试工单草稿，设备是 E2E 浏览器，描述为验证 Agent 页面意图。',
      '工单请求',
    )
    await page.getByTestId('agent-draft-card').waitFor()
    await page.screenshot({
      path: path.join(screenshotDir, 'agent-four-intents.png'),
      fullPage: true,
    })

    await context.close()
    assert.deepEqual(consoleErrors, [])
    console.log('agent-flow: four intent UI passed')
  } else {
    throw new Error(`Unknown E2E_PHASE: ${phase}`)
  }
} finally {
  await browser.close()
}
