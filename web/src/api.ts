import type { DonePayload, InspectResponse, Mode, Status, Student } from './types'

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as { detail?: string }
      detail = body.detail ?? detail
    } catch {
      // A plain HTTP status is still an honest, useful failure state.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const getStatus = () => jsonRequest<Status>('/api/status')
export const getStudents = () => jsonRequest<Student[]>('/api/students')

export function inspectPrompt(
  userId: string,
  message: string,
  sessionId: string,
  signal?: AbortSignal,
) {
  return jsonRequest<InspectResponse>('/api/inspect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, message, session_id: sessionId }),
    signal,
  })
}

interface StreamHandlers {
  onText: (text: string) => void
  onDone: (payload: DonePayload) => void
  onError: (detail: string) => void
}

export async function streamChat(
  body: { user_id: string; session_id: string; message: string; mode: Mode },
  handlers: StreamHandlers,
) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const payload = (await response.json()) as { detail?: string }
      detail = payload.detail ?? detail
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw new Error(detail)
  }
  if (!response.body) throw new Error('The chat response did not include a stream.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (raw: string) => {
    const lines = raw.replaceAll('\r', '').split('\n')
    let event = 'message'
    const data: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!data.length) return
    const payload = JSON.parse(data.join('\n')) as Record<string, unknown>
    if (event === 'text') handlers.onText(String(payload.text ?? ''))
    if (event === 'done') handlers.onDone(payload as unknown as DonePayload)
    if (event === 'error') handlers.onError(String(payload.detail ?? 'The tutor could not respond.'))
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const events = buffer.split(/\r?\n\r?\n/)
    buffer = events.pop() ?? ''
    for (const event of events) dispatch(event)
    if (done) break
  }
  if (buffer.trim()) dispatch(buffer)
}
