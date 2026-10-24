export class ApiError extends Error {
  status: number
  runId?: string

  constructor(status: number, message: string, runId?: string) {
    super(message)
    this.status = status
    this.runId = runId
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail.replace(/^Value error,\s*/, '')
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  if (Array.isArray(detail)) {
    return detail.map((item) => detailMessage(item?.msg)).filter(Boolean).join('；')
  }
  return '请求未完成，请稍后重试'
}

export async function apiError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null)
  return new ApiError(response.status, detailMessage(body?.detail),
    typeof body?.detail?.run_id === 'string' ? body.detail.run_id : undefined)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    throw await apiError(response)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  }),
}
