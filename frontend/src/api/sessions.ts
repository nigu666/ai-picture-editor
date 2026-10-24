import { api } from './client'
import type { ColorSettings } from './colors'
import type { Asset } from './assets'

type LayerBase = {
  id: string; name?: string; width: number; height: number; locked: boolean
  visible: boolean; opacity: number
  transform: { x: number; y: number; scale_x: number; scale_y: number; rotation: number }
}
export type CanvasLayer = LayerBase & ({ kind?: 'image'; asset_id: string; adjustments?: Partial<ColorSettings> } | {
  kind: 'text'; asset_id?: null; text: string; font_family: 'yahei'; font_size: number; fill: string; align: 'left' | 'center' | 'right'
})
export type CanvasDocument = {
  schema_version?: 1
  adjustments?: Partial<ColorSettings>
  width: number; height: number
  layers: CanvasLayer[]
}
export type SessionSummary = {
  id: string; title: string; original_asset_id: string; current_asset_id: string
  revision: number; history_seq: number; created_at: string; updated_at: string
}
export type EditSession = SessionSummary & {
  document: CanvasDocument; previous_document: CanvasDocument | null
  assets: Asset[]; can_undo: boolean; can_redo: boolean; history_limit: number
  history: { seq: number; action: string; current_asset_id: string; created_at: string }[]
}
export const sessionsApi = {
  list: () => api.get<SessionSummary[]>('/sessions'),
  get: (id: string) => api.get<EditSession>(`/sessions/${id}`),
  create: (asset: Asset, ids: string[]) => api.post<EditSession>('/sessions', {
    current_asset_id: asset.id, asset_ids: ids, title: `创作 · ${asset.width} × ${asset.height}`,
  }),
  change: (id: string, action: 'adopt' | 'assets' | 'undo' | 'redo' | 'rename' | 'layers', body: object) =>
    api.post<EditSession>(`/sessions/${id}/${action}`, body),
}
