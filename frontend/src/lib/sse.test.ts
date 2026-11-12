import { describe, expect, it } from 'vitest'

import { SSEParser } from './sse'

describe('SSEParser', () => {
  it('parses multiple complete events from one network chunk', () => {
    const parser = new SSEParser()
    const frames = parser.push(
      'event: meta\ndata: {"request_id":"one"}\n\n' +
        'event: token\ndata: {"text":"hello"}\n\n',
    )

    expect(frames).toEqual([
      { event: 'meta', data: '{"request_id":"one"}' },
      { event: 'token', data: '{"text":"hello"}' },
    ])
  })

  it('handles CRLF separators and boundaries split across chunks', () => {
    const parser = new SSEParser()

    expect(
      parser.push('event: meta\r\ndata: {"request_id":"abc"}\r\n\r'),
    ).toEqual([])
    expect(
      parser.push('\nevent: token\r\ndata: {"text":"你'),
    ).toEqual([
      { event: 'meta', data: '{"request_id":"abc"}' },
    ])
    expect(parser.push('好"}\r\n\r\n')).toEqual([
      { event: 'token', data: '{"text":"你好"}' },
    ])
  })

  it('combines multiple data lines and ignores comments', () => {
    const parser = new SSEParser()
    const frames = parser.push(
      ': keep-alive\nevent: token\ndata: line one\ndata: line two\n\n',
    )

    expect(frames).toEqual([
      { event: 'token', data: 'line one\nline two' },
    ])
  })

  it('flushes a final complete frame without a trailing blank line', () => {
    const parser = new SSEParser()
    parser.push('event: done\ndata: {"request_id":"abc"}')

    expect(parser.finish()).toEqual([
      { event: 'done', data: '{"request_id":"abc"}' },
    ])
  })
})

