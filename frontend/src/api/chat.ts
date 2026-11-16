import { SSEParser, type SSEFrame } from '../lib/sse'

export interface StreamMeta {
  request_id: string
  model: string
  created_at: string
}

export interface StreamToken {
  text: string
}

export interface StreamUsage {
  prompt_tokens: number
  completion_tokens: number
}

export interface StreamDone {
  request_id: string
}

export interface StreamError {
  request_id: string
  code: string
  message: string
}

export type ChatStreamEvent =
  | { event: 'meta'; data: StreamMeta }
  | { event: 'token'; data: StreamToken }
  | { event: 'usage'; data: StreamUsage }
  | { event: 'done'; data: StreamDone }
  | { event: 'error'; data: StreamError }

interface ErrorResponse {
  error?: {
    code?: string
    message?: string
  }
  detail?: string | Array<{ msg?: string }>
}

const SUPPORTED_EVENTS = new Set([
  'meta',
  'token',
  'usage',
  'done',
  'error',
])
const STREAM_IDLE_TIMEOUT_MS = 45_000

function parseFrame(frame: SSEFrame): ChatStreamEvent | null {
  if (!SUPPORTED_EVENTS.has(frame.event)) {
    return null
  }

  let data: unknown
  try {
    data = JSON.parse(frame.data)
  } catch {
    throw new Error('服务端返回了无法解析的 SSE 数据。')
  }

  return {
    event: frame.event,
    data,
  } as ChatStreamEvent
}

export async function readSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  const reader = stream.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = new SSEParser()
  let terminalEventReceived = false

  const handleFrames = (frames: SSEFrame[]) => {
    for (const frame of frames) {
      const event = parseFrame(frame)
      if (event === null) {
        continue
      }
      if (event.event === 'done' || event.event === 'error') {
        terminalEventReceived = true
      }
      onEvent(event)
      if (terminalEventReceived) {
        break
      }
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        break
      }
      handleFrames(parser.push(decoder.decode(value, { stream: true })))
      if (terminalEventReceived) {
        try {
          await reader.cancel()
        } catch {
          // The terminal event is authoritative even if cancellation races.
        }
        break
      }
    }

    const tail = decoder.decode()
    if (tail) {
      handleFrames(parser.push(tail))
    }
    handleFrames(parser.finish())
  } finally {
    reader.releaseLock()
  }

  if (!terminalEventReceived) {
    throw new Error('流式响应在完成事件之前意外结束，请稍后重试。')
  }
}

function errorMessageFromBody(body: ErrorResponse, status: number): string {
  if (body.error?.message) {
    return body.error.message
  }
  if (typeof body.detail === 'string') {
    return body.detail
  }
  if (Array.isArray(body.detail) && body.detail[0]?.msg) {
    return body.detail[0].msg
  }
  return `请求失败（HTTP ${status}）。`
}

export async function streamChat(options: {
  message: string
  signal?: AbortSignal
  idleTimeoutMs?: number
  onEvent: (event: ChatStreamEvent) => void
}): Promise<void> {
  const controller = new AbortController()
  const idleTimeoutMs = options.idleTimeoutMs ?? STREAM_IDLE_TIMEOUT_MS
  let idleTimeout: ReturnType<typeof setTimeout> | undefined
  let timedOut = false

  const abortFromCaller = () => controller.abort()
  if (options.signal?.aborted) {
    controller.abort()
  } else {
    options.signal?.addEventListener('abort', abortFromCaller, {
      once: true,
    })
  }

  const resetIdleTimeout = () => {
    if (idleTimeout !== undefined) {
      clearTimeout(idleTimeout)
    }
    idleTimeout = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, idleTimeoutMs)
  }

  try {
    resetIdleTimeout()
    const response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message: options.message }),
      signal: controller.signal,
    })

    if (!response.ok) {
      let errorBody: ErrorResponse = {}
      try {
        errorBody = (await response.json()) as ErrorResponse
      } catch {
        // The status code is still enough to provide a useful fallback.
      }
      throw new Error(errorMessageFromBody(errorBody, response.status))
    }

    if (!response.body) {
      throw new Error('当前浏览器没有收到可读取的流式响应。')
    }

    await readSseStream(response.body, (event) => {
      resetIdleTimeout()
      options.onEvent(event)
    })
  } catch (error) {
    if (timedOut) {
      throw new Error('模型响应超时，请稍后重试。')
    }
    throw error
  } finally {
    if (idleTimeout !== undefined) {
      clearTimeout(idleTimeout)
    }
    options.signal?.removeEventListener('abort', abortFromCaller)
  }
}

