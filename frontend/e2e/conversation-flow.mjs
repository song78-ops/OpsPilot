import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { chromium } from 'playwright-core'

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const phase = process.argv[2] || 'prepare'
const screenshotDir = path.resolve('e2e/artifacts')
const statePath = path.join(screenshotDir, 'conversation-flow-state.json')
const lastConversationKey = 'opspilot.agent.lastConversationId'
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
  const initialBudget = await page.evaluate(async () => {
    const response = await fetch('/api/v1/health/llm-budget')
    return response.json()
  })
  assert.equal(initialBudget.provider, 'mock')
  assert.equal(initialBudget.budget.requests_used, 0)
  await page.getByTestId('nav-agent').click()
  await page.getByRole('heading', {
    name: '工单助手',
    level: 1,
  }).waitFor()
  await page.getByTestId('agent-conversation-list').waitFor()
}

async function assertZeroPaidUsage(page) {
  const budget = await page.evaluate(async () => {
    const response = await fetch('/api/v1/health/llm-budget')
    return response.json()
  })
  assert.equal(budget.provider, 'mock')
  assert.equal(budget.budget.requests_used, 0)
  assert.equal(budget.budget.total_tokens_used, 0)
}

async function submitPrompt(page, prompt) {
  const before = await page
    .locator('[data-testid="agent-history-message"][data-role="assistant"]')
    .count()
  await page.getByTestId('agent-input').fill(prompt)
  await page.getByTestId('agent-run').click()
  await page.waitForFunction(
    (previous) => (
      document.querySelectorAll(
        '[data-testid="agent-history-message"][data-role="assistant"]',
      ).length > previous
    ),
    before,
    { timeout: 180_000 },
  )
  await page.getByTestId('agent-run').waitFor({ state: 'visible' })
  assert.equal(await page.getByTestId('agent-error').count(), 0)
}

async function currentConversationId(page) {
  return (
    await page.getByTestId('agent-current-conversation-id').innerText()
  ).trim()
}

async function fetchDraft(page, draftId) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/tickets/drafts/${id}`)
    if (!response.ok) {
      throw new Error(`Draft API failed with ${response.status}`)
    }
    return response.json()
  }, draftId)
}

async function fetchHistory(page, conversationId) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/agent/conversations/${id}`)
    if (!response.ok) {
      throw new Error(`Conversation API failed with ${response.status}`)
    }
    return response.json()
  }, conversationId)
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

  await page.getByTestId('nav-knowledge').click()
  await page.getByRole('heading', { name: '企业知识库', level: 1 }).waitFor()
  await page.getByTestId('document-row').first().waitFor({ timeout: 60_000 })
  await page.getByTestId('rag-question-input').fill('缓存击穿应该怎么处理？')
  await page.getByTestId('rag-ask-button').click()
  await page.getByTestId('rag-result').last().waitFor({ timeout: 180_000 })
  assert.equal(await page.getByTestId('rag-error').count(), 0)
}

const browser = await chromium.launch({
  executablePath: edgePath,
  headless: true,
})

try {
  if (phase === 'prepare') {
    const { context, page } = await launchPage(browser)
    await openAgent(page)
    await page.getByTestId('agent-new-conversation').click()
    assert.ok((await page.getByTestId('agent-conversation-title').innerText()).includes('新会话'))

    const marker = Date.now()
    await submitPrompt(page, '帮我创建一个电脑无法联网的工单。')
    const conversationId = await currentConversationId(page)
    assert.match(conversationId, /^[0-9a-f]{32}$/)
    assert.equal(
      await page.evaluate((key) => localStorage.getItem(key), lastConversationKey),
      conversationId,
    )
    const draftRow = page.getByTestId('ticket-draft-row').first()
    await draftRow.waitFor({ timeout: 60_000 })
    const draftId = (await draftRow.getAttribute('data-draft-id')) ?? ''
    assert.match(draftId, /^[0-9a-f]{32}$/)

    await submitPrompt(
      page,
      '把刚才那个工单改成无法连接 Wi-Fi。',
    )
    const updatedDraft = await fetchDraft(page, draftId)
    assert.match(updatedDraft.description, /Wi-Fi/i)
    assert.equal(updatedDraft.version, 2)

    const history = await fetchHistory(page, conversationId)
    assert.equal(history.total, 6)
    assert.deepEqual(
      history.messages.map((message) => message.role),
      ['user', 'tool', 'assistant', 'user', 'tool', 'assistant'],
    )

    await page.reload({ waitUntil: 'networkidle' })
    await page.getByTestId('nav-agent').click()
    await page.getByTestId('agent-conversation-title').waitFor()
    await page.waitForFunction(
      (expected) => (
        document.querySelector(
          '[data-testid="agent-current-conversation-id"]',
        )?.textContent?.trim() === expected
      ),
      conversationId,
      { timeout: 60_000 },
    )
    assert.equal(
      await page.getByTestId('agent-history-message').count(),
      6,
    )
    assert.ok(
      (await page.getByTestId('agent-message-timeline').innerText())
        .includes('把刚才那个工单改成无法连接 Wi-Fi'),
    )

    await writeFile(
      statePath,
      JSON.stringify({ conversationId, draftId, marker }, null, 2),
      'utf8',
    )
    await assertZeroPaidUsage(page)
    await page.screenshot({
      path: path.join(screenshotDir, 'conversation-restored-after-refresh.png'),
      fullPage: true,
    })
    await context.close()
    console.log('conversation-flow: prepare passed')
  } else if (phase === 'resume') {
    const state = JSON.parse(await readFile(statePath, 'utf8'))
    const { context, page } = await launchPage(browser)
    await openAgent(page)

    await page.waitForFunction(
      (expected) => (
        document.querySelector(
          '[data-testid="agent-current-conversation-id"]',
        )?.textContent?.trim() === expected
      ),
      state.conversationId,
      { timeout: 60_000 },
    )
    assert.equal(
      await page.getByTestId('agent-history-message').count(),
      6,
    )
    const persistedDraft = await fetchDraft(page, state.draftId)
    assert.match(persistedDraft.description, /Wi-Fi/i)
    assert.equal(persistedDraft.version, 2)

    await page.getByTestId('agent-new-conversation').click()
    await submitPrompt(page, '你好，介绍一下你自己。')
    const secondConversationId = await currentConversationId(page)
    assert.notEqual(secondConversationId, state.conversationId)
    assert.equal(
      await page.getByTestId('agent-history-message').count(),
      2,
    )

    await page
      .locator(
        `[data-testid="agent-conversation-item"][data-conversation-id="${state.conversationId}"]`,
      )
      .click()
    await page.waitForFunction(
      (expected) => (
        document.querySelector(
          '[data-testid="agent-current-conversation-id"]',
        )?.textContent?.trim() === expected
      ),
      state.conversationId,
      { timeout: 60_000 },
    )
    assert.equal(
      await page.getByTestId('agent-history-message').count(),
      6,
    )
    assert.ok(
      (await page.getByTestId('agent-message-timeline').innerText())
        .includes('无法连接 Wi-Fi'),
    )
    assert.notEqual(
      await page.evaluate((key) => localStorage.getItem(key), lastConversationKey),
      secondConversationId,
    )

    await page.screenshot({
      path: path.join(screenshotDir, 'conversation-restored-after-restart.png'),
      fullPage: true,
    })
    await smokeExistingPages(page)
    await writeFile(
      path.join(screenshotDir, 'conversation-flow-result.json'),
      JSON.stringify(
        {
          first_conversation_id: state.conversationId,
          second_conversation_id: secondConversationId,
          draft_id: state.draftId,
          draft_description: persistedDraft.description,
          draft_version: persistedDraft.version,
        },
        null,
        2,
      ),
      'utf8',
    )
    await assertZeroPaidUsage(page)
    await context.close()
    assert.deepEqual(consoleErrors, [])
    console.log('conversation-flow: resume passed')
  } else {
    throw new Error(`Unknown conversation E2E phase: ${phase}`)
  }
} finally {
  await browser.close()
}
