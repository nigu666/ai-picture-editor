import { api } from './client'
import type { Run, RunProgress } from './runs'
import type { CanvasDocument, EditSession } from './sessions'

export type PromoteInput = { prompt: string; selection_version: number; request_id: string }
export type PromoteRun = Run & { request: PromoteInput }
export type PromoteProgress = RunProgress & { result: Run['result'] & { layer_document?: CanvasDocument; applied_revision?: number; object_asset_id?: string; background_asset_id?: string } }
export const promoteApi = {
  options: () => api.get<{ enabled: boolean; model: string; local_repair?: boolean }>('/promote-options'),
  list: (id: string) => api.get<PromoteRun[]>(`/sessions/${id}/promote-runs`),
  submit: (id: string, revision: number, params: PromoteInput) => api.post<{ run: Run }>(`/sessions/${id}/tools/promote_object`, { revision, params }),
  resume: (id: string, run: string) => api.post<{ run: Run }>(`/sessions/${id}/promote-runs/${run}/resume`),
  apply: (id: string, run: string, revision: number) => api.post<EditSession>(`/sessions/${id}/promote-runs/${run}/apply`, { revision }),
}
