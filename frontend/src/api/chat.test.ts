import { describe, expect, it } from 'vitest'

import { readSseStream, type ChatStreamEvent } from './chat'

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
})

