import { api } from './client'
import type { Run } from './runs'

export type RegionKind = 'erase_region' | 'replace_region'
export type RegionInput = { prompt: string; selection_version: number; request_id: string }
export type RegionRun = Run & { request: RegionInput }
export const regionApi = {
  options: () => api.get<{ enabled: boolean; model: string }>('/region-options'),
  list: (id: string) => api.get<RegionRun[]>(`/sessions/${id}/region-runs`),
  submit: (id: string, revision: number, kind: RegionKind, params: RegionInput) => api.post<{ run: Run }>(`/sessions/${id}/tools/${kind}`, { revision, params }),
  resume: (id: string, runId: string) => api.post<{ run: Run }>(`/sessions/${id}/region-runs/${runId}/resume`),
}
