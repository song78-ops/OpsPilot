import { afterEach, describe, expect, it, vi } from 'vitest'
import { watch } from 'vue'

import { useChat } from './useChat'

const encoder = new TextEncoder()

function event(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`
}

function responseFromChunks(chunks: string[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useChat', () => {
  it('appends token events and completes on done', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        responseFromChunks([
          event('meta', {
            request_id: 'r1',
            model: 'deepseek-chat',
            created_at: 'now',
          }),
          event('token', { text: '你' }),
          event('token', { text: '好' }),
          event('usage', { prompt_tokens: 4, completion_tokens: 2 }),
          event('done', { request_id: 'r1' }),
        ]),
      ),
    )
    const chat = useChat()
    const observedStatuses: string[] = []
    watch(
      () => chat.messages.value[1]?.status,
      (status) => {
        if (status) {
          observedStatuses.push(status)
        }
      },
      { flush: 'sync' },
    )

    await chat.sendMessage('测试消息')

    expect(chat.messages.value).toHaveLength(2)
    expect(chat.messages.value[0].content).toBe('测试消息')
    expect(chat.messages.value[1]).toMatchObject({
      role: 'assistant',
      content: '你好',
      status: 'complete',
      usage: { prompt_tokens: 4, completion_tokens: 2 },
    })
    expect(chat.isGenerating.value).toBe(false)
    expect(observedStatuses).toContain('complete')
  })

  it('shows a friendly error event without pretending the answer completed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        responseFromChunks([
          event('meta', {
            request_id: 'r2',
            model: 'deepseek-chat',
            created_at: 'now',
          }),
          event('error', {
            request_id: 'r2',
            code: 'LLM_TIMEOUT',
            message: 'upstream timeout',
          }),
        ]),
      ),
    )
    const chat = useChat()

    await chat.sendMessage('测试错误')

    expect(chat.messages.value[1].status).toBe('error')
    expect(chat.messages.value[1].error).toContain('模型响应超时')
    expect(chat.isGenerating.value).toBe(false)
  })

  it('ends loading when the stream closes without a terminal event', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        responseFromChunks([
          event('meta', {
            request_id: 'r-broken',
            model: 'deepseek-chat',
            created_at: 'now',
          }),
        ]),
      ),
    )
    const chat = useChat()

    await chat.sendMessage('测试意外结束')

    expect(chat.messages.value[1].status).toBe('error')
    expect(chat.messages.value[1].error).toContain('意外结束')
    expect(chat.isGenerating.value).toBe(false)
  })

  it('stops an in-progress request with AbortController', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        const signal = init?.signal
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                event('meta', {
                  request_id: 'r3',
                  model: 'deepseek-chat',
                  created_at: 'now',
                }) + event('token', { text: '开始' }),
              ),
            )
            signal?.addEventListener('abort', () => {
              controller.error(new DOMException('Aborted', 'AbortError'))
            })
          },
          pull() {
            return new Promise<void>(() => undefined)
          },
        })
        return Promise.resolve(
          new Response(stream, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
          }),
        )
      }),
    )
    const chat = useChat()

    const pending = chat.sendMessage('长问题')
    await vi.waitFor(() => {
      expect(chat.messages.value[1]?.content).toBe('开始')
    })
    chat.stopGeneration()
    await pending

    expect(chat.messages.value[1].status).toBe('stopped')
    expect(chat.isGenerating.value).toBe(false)

    chat.clearConversation()
    expect(chat.messages.value).toHaveLength(0)
  })
})

