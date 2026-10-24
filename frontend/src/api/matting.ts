import { api } from './client'
import type { Run } from './runs'

export const mattingApi = {
  list: (id: string) => api.get<Run[]>(`/sessions/${encodeURIComponent(id)}/matting-runs`),
  submit: (id: string, revision: number) => api.post<{ run: Run }>(`/sessions/${encodeURIComponent(id)}/tools/remove_background`, { revision, params: {} }),
}
