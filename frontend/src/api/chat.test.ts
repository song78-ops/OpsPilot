import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  readSseStream,
  streamChat,
  type ChatStreamEvent,
} from './chat'

function streamFromByteChunks(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk)
      }
      controller.close()
    },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('readSseStream', () => {
  it('decodes split UTF-8 bytes and events merged in one chunk', async () => {
    const payload =
      'event: meta\n' +
      'data: {"request_id":"r1","model":"deepseek-chat","created_at":"now"}\n\n' +
      'event: token\n' +
      'data: {"text":"你好"}\n\n' +
      'event: done\n' +
      'data: {"request_id":"r1"}\n\n'
    const encoder = new TextEncoder()
    const bytes = encoder.encode(payload)
    const chineseByteStart = encoder.encode(
      payload.slice(0, payload.indexOf('你好')),
    ).length
    const splitPoints = [
      3,
      19,
      41,
      46,
      72,
      chineseByteStart + 1,
      chineseByteStart + 4,
      bytes.length,
    ].sort((a, b) => a - b)
    const chunks: Uint8Array[] = []
    let start = 0
    for (const end of splitPoints) {
      chunks.push(bytes.slice(start, end))
      start = end
    }

    const events: ChatStreamEvent[] = []
    await readSseStream(streamFromByteChunks(chunks), (event) => {
      events.push(event)
    })

    expect(events.map((event) => event.event)).toEqual([
      'meta',
      'token',
      'done',
    ])
    expect(events[1]).toEqual({
      event: 'token',
      data: { text: '你好' },
    })
  })

  it('rejects a stream that ends without done or error', async () => {
    const payload =
      'event: meta\n' +
      'data: {"request_id":"r1","model":"deepseek-chat","created_at":"now"}\n\n'
    const bytes = new TextEncoder().encode(payload)

    await expect(
      readSseStream(streamFromByteChunks([bytes]), () => undefined),
    ).rejects.toThrow('完成事件之前意外结束')
  })

  it('stops reading immediately after a terminal event', async () => {
    let cancelled = false
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: done\ndata: {"request_id":"r1"}\n\n',
          ),
        )
      },
      cancel() {
        cancelled = true
      },
    })

    const events: ChatStreamEvent[] = []
    await readSseStream(stream, (event) => {
      events.push(event)
    })

    expect(events.map((event) => event.event)).toEqual(['done'])
    expect(cancelled).toBe(true)
  })
})

describe('streamChat', () => {
  it('aborts a 200 response that stops producing events', async () => {
    const encoder = new TextEncoder()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              'event: meta\n' +
                'data: {"request_id":"r1","model":"fake",' +
                '"created_at":"now"}\n\n',
            ),
          )
          init?.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('Aborted', 'AbortError'))
          })
        },
      })
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      streamChat({
        message: '测试超时',
        idleTimeoutMs: 20,
        onEvent: () => undefined,
      }),
    ).rejects.toThrow('模型响应超时')
  })
})

