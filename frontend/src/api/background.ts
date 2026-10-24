import { api } from './client'
import type { Run } from './runs'

export type BackgroundInput = { prompt: string; count: number }
export type BackgroundRun = Run & { request: BackgroundInput }
export const backgroundApi = {
  options: () => api.get<{ enabled: boolean; provider: string; label: string; model: string; counts: number[]; prompt_limit: number }>('/background-options'),
  list: (id: string) => api.get<BackgroundRun[]>(`/sessions/${encodeURIComponent(id)}/background-runs`),
  submit: (id: string, revision: number, params: BackgroundInput) => api.post<{ run: Run }>(`/sessions/${encodeURIComponent(id)}/tools/replace_background`, { revision, params }),
}
