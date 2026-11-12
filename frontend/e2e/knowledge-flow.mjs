import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

import { chromium } from 'playwright-core'

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const screenshotDir = path.resolve('e2e/artifacts')
const consoleErrors = []
const uploadedName = 'e2e_knowledge_demo.txt'
const documentContent = `OpsPilot E2E 知识库验收文档

Redis 缓存击穿可以通过互斥锁、逻辑过期和热点数据预热处理。缓存过期时间应增加随机抖动，避免大量键同时失效。

文档内容只用于非敏感浏览器验收。`

await mkdir(screenshotDir, { recursive: true })
const browser = await chromium.launch({
  executablePath: edgePath,
  headless: true,
})

try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
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

  await page.goto(baseUrl, { waitUntil: 'networkidle' })
  assert.equal(await page.getByTestId('nav-chat').isVisible(), true)
  await page.getByTestId('chat-input').fill('只回复 OK')
  await page.getByTestId('chat-send').click()
  await page.waitForFunction(
    () => document.querySelectorAll('.message-row').length >= 2,
    undefined,
    { timeout: 180_000 },
  )
  await page.getByTestId('chat-send').waitFor({ timeout: 180_000 })
  const assistantText = await page.locator('.message-content').last().innerText()
  assert.ok(assistantText.trim().length > 0)

  await page.getByTestId('nav-knowledge').click()
  await page.getByText('企业知识库', { exact: true }).waitFor()

  await page.getByTestId('document-file-input').setInputFiles({
    name: uploadedName,
    mimeType: 'text/plain',
    buffer: Buffer.from(documentContent, 'utf8'),
  })
  await page.getByTestId('document-upload-button').click()
  await page.getByText(/上传成功/).waitFor({ timeout: 60_000 })

  const documentRow = page
    .getByTestId('document-row')
    .filter({ hasText: uploadedName })
    .first()
  await documentRow.waitFor({ timeout: 60_000 })
  await documentRow.locator('input[type="checkbox"]').check()
  await page.getByTestId('index-selected-button').click()
  await documentRow.getByText('本次已索引').waitFor({ timeout: 180_000 })

  await page.getByTestId('rag-question-input').fill(
    '文档中缓存击穿有哪些处理方法？',
  )
  await page.getByTestId('rag-ask-button').click()
  await page.getByTestId('rag-answer').waitFor({ timeout: 180_000 })
  await page.getByText(/互斥锁/).first().waitFor()
  await page.getByText(uploadedName).first().waitFor()
  assert.match(
    await page.getByTestId('rag-answer').innerText(),
    /互斥锁|逻辑过期|预热/,
  )
  await page.screenshot({
    path: path.join(screenshotDir, 'knowledge-answered.png'),
    fullPage: true,
  })
  await page.getByTestId('rag-result').first().screenshot({
    path: path.join(screenshotDir, 'knowledge-answer-card.png'),
  })

  await page.getByTestId('rag-question-input').fill(
    '公司的员工差旅报销标准是多少？',
  )
  await page.getByTestId('rag-ask-button').click()
  await page.waitForFunction(
    () => document.querySelectorAll('[data-testid="rag-result"]').length >= 2,
    undefined,
    { timeout: 180_000 },
  )
  const latestResult = page.getByTestId('rag-result').last()
  await latestResult.getByText('证据不足').waitFor()
  await latestResult.getByText('知识库中没有找到足够依据').waitFor()
  await page.screenshot({
    path: path.join(screenshotDir, 'knowledge-insufficient.png'),
    fullPage: true,
  })
  await latestResult.screenshot({
    path: path.join(screenshotDir, 'knowledge-insufficient-card.png'),
  })

  await page.screenshot({
    path: path.join(screenshotDir, 'knowledge-desktop.png'),
    fullPage: true,
  })
  await context.close()

  const mobileContext = await browser.newContext({
    viewport: { width: 480, height: 900 },
    locale: 'zh-CN',
  })
  const mobilePage = await mobileContext.newPage()
  await mobilePage.goto(baseUrl, { waitUntil: 'networkidle' })
  await mobilePage.getByTestId('nav-knowledge').click()
  await mobilePage.getByText('企业知识库', { exact: true }).waitFor()
  await mobilePage.screenshot({
    path: path.join(screenshotDir, 'knowledge-mobile.png'),
    fullPage: true,
  })
  await mobilePage.getByTestId('rag-question-input').scrollIntoViewIfNeeded()
  await mobilePage.screenshot({
    path: path.join(screenshotDir, 'knowledge-mobile-rag.png'),
  })
  await mobileContext.close()

  assert.deepEqual(consoleErrors, [])
  console.log('browser-flow: passed')
  console.log(`desktop-screenshot: ${path.join(screenshotDir, 'knowledge-desktop.png')}`)
  console.log(`answered-screenshot: ${path.join(screenshotDir, 'knowledge-answered.png')}`)
  console.log(`answer-card-screenshot: ${path.join(screenshotDir, 'knowledge-answer-card.png')}`)
  console.log(`insufficient-screenshot: ${path.join(screenshotDir, 'knowledge-insufficient.png')}`)
  console.log(`insufficient-card-screenshot: ${path.join(screenshotDir, 'knowledge-insufficient-card.png')}`)
  console.log(`mobile-screenshot: ${path.join(screenshotDir, 'knowledge-mobile.png')}`)
  console.log(`mobile-rag-screenshot: ${path.join(screenshotDir, 'knowledge-mobile-rag.png')}`)
} finally {
  await browser.close()
}

