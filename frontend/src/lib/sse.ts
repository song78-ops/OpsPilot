export interface SSEFrame {
  event: string
  data: string
}

interface Boundary {
  index: number
  length: number
}

function findBoundary(buffer: string): Boundary | null {
  const match = /\r\n\r\n|\n\n|\r\r/.exec(buffer)
  if (!match || match.index === undefined) {
    return null
  }
  return {
    index: match.index,
    length: match[0].length,
  }
}

export class SSEParser {
  private buffer = ''

  push(chunk: string): SSEFrame[] {
    this.buffer += chunk
    const frames: SSEFrame[] = []

    while (true) {
      const boundary = findBoundary(this.buffer)
      if (boundary === null) {
        break
      }

      const block = this.buffer.slice(0, boundary.index)
      this.buffer = this.buffer.slice(boundary.index + boundary.length)
      const frame = this.parseBlock(block)
      if (frame !== null) {
        frames.push(frame)
      }
    }

    return frames
  }

  finish(): SSEFrame[] {
    const remainder = this.buffer.trim()
    this.buffer = ''
    if (!remainder) {
      return []
    }

    const frame = this.parseBlock(remainder)
    return frame === null ? [] : [frame]
  }

  private parseBlock(block: string): SSEFrame | null {
    let event = 'message'
    const dataLines: string[] = []

    for (const line of block.split(/\r\n|\n|\r/)) {
      if (!line || line.startsWith(':')) {
        continue
      }

      const separator = line.indexOf(':')
      const field = separator === -1 ? line : line.slice(0, separator)
      let value = separator === -1 ? '' : line.slice(separator + 1)
      if (value.startsWith(' ')) {
        value = value.slice(1)
      }

      if (field === 'event') {
        event = value || 'message'
      } else if (field === 'data') {
        dataLines.push(value)
      }
    }

    if (dataLines.length === 0) {
      return null
    }

    return {
      event,
      data: dataLines.join('\n'),
    }
  }
}

