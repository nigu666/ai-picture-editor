import { api } from './client'

export type SelectionPoint = [number, number]
export type SamPoint = { x: number; y: number; label: 0 | 1 }
export type SelectionStroke = { points: SelectionPoint[]; radius: number; mode: 'add' | 'subtract' }
export type SelectionState = { revision: number; version: number; width: number; height: number; has_selection: boolean; selected_pixels: number; can_undo: boolean; can_redo: boolean; history_limit: number; sam_prompts: SamPoint[] }
export type SelectionCommand = { revision: number; version: number; request_id: string } & (SelectionStroke | { prompts: SamPoint[] } | { action: 'undo' | 'redo' | 'clear' })
export const selectionKey = (user: string, id: string, revision: number) => ['selection', user, id, revision]
export const selectionApi = {
  get: (id: string, revision: number) => api.get<SelectionState>(`/sessions/${id}/selection?revision=${revision}`),
  change: (id: string, body: SelectionCommand) => api.post<SelectionState>(`/sessions/${id}/selection/${'action' in body ? 'actions' : 'prompts' in body ? 'points' : 'strokes'}`, body),
  prepare: (id: string, revision: number) => api.post<{ revision: number; ready: boolean; cache_hit: boolean }>(`/sessions/${id}/selection/prepare`, { revision }),
  mask: (id: string, revision: number, version: number) => `/api/sessions/${id}/selection/mask?revision=${revision}&version=${version}&preview=true`,
}

export type SelectionDrawing = { active: boolean; disabled: boolean; radius: number; mode: 'add' | 'subtract'; tool?: 'brush' | 'sam'; samPoints?: SamPoint[]; onPoint?: (point: SelectionPoint) => void; overlayUrl?: string; pendingStroke?: SelectionStroke; onStroke: (stroke: SelectionStroke) => void }
