export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
}

export type MessageRole = 'user' | 'assistant'
export type MessageStatus = 'streaming' | 'complete' | 'error' | 'stopped'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  status: MessageStatus
  error?: string
  usage?: TokenUsage
}

