import { api } from './client'
import type { Asset } from './assets'

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type GenerateInput = {
  prompt: string
  ratio: '1:1' | '4:5' | '3:4' | '9:16' | '16:9'
  count: number
  seed?: number
  negative_prompt?: string
  reference_asset_ids?: string[]
}
export type GenerationRecord = {
  id: string; created_at: string; status: RunStatus; stage: string; progress: number
  provider: string; model: string | null; prompt: string; ratio: GenerateInput['ratio'] | null
  width: number; height: number; count: number; seed: number | null; negative_prompt: string | null
  reference_asset_ids?: string[]
}
export type GenerationPage = { items: GenerationRecord[]; next_cursor: string | null }
export const generationHistoryKey = (userId: string) => ['generation-history', userId]
export type Run = {
  id: string
  tool: string
  status: RunStatus
  progress: number
  stage: string
  provider: string
  result: { model?: string; generation_mode?: 'text' | 'reference'; asset_ids?: string[]; is_mock?: boolean; source_revision?: number; recoverable?: boolean; remote_task_id?: string; query_attempt?: number; submission_started?: boolean; selection_version?: number; selected_pixels?: number }
  error: string | null
  candidates: Asset[]
}
export type RunProgress = Omit<Run, 'candidates'>
export const isTerminal = (status?: RunStatus) => status === 'succeeded' || status === 'failed'
export const runKey = (userId: string, runId: string) => ['run', userId, runId]
export const runsApi = {
  history: (before: string | null) => api.get<GenerationPage>(`/generations${before ? `?before=${encodeURIComponent(before)}` : ''}`),
  generate: (input: GenerateInput) => api.post<Run>('/generations', input),
  get: (id: string) => api.get<Run>(`/runs/${encodeURIComponent(id)}`),
}
