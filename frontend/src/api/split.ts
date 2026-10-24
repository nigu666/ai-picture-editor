import { api } from './client'
import type { Run, RunProgress } from './runs'
import type { CanvasDocument, EditSession } from './sessions'

export type SplitInput = { prompt: string; request_id: string }
export type SplitRun = Run & { request: SplitInput }
export type SplitProgress = RunProgress & { result: Run['result'] & { layer_document?: CanvasDocument; applied_revision?: number } }
export const splitApi = {
  options: () => api.get<{ enabled: boolean; model: string; local_repair?: boolean }>('/split-options'),
  list: (id: string) => api.get<SplitRun[]>(`/sessions/${id}/split-runs`),
  submit: (id: string, revision: number, params: SplitInput) => api.post<{ run: Run }>(`/sessions/${id}/tools/split_layers`, { revision, params }),
  resume: (id: string, run: string) => api.post<{ run: Run }>(`/sessions/${id}/split-runs/${run}/resume`),
  apply: (id: string, run: string, revision: number) => api.post<EditSession>(`/sessions/${id}/split-runs/${run}/apply`, { revision }),
}
