import { apiError } from './client'
import type { CanvasDocument } from './sessions'
import { placementOf } from './layout'

export type ImageLayer = CanvasDocument['layers'][number]
export type LayerEdit = { layer_id: string; visible?: boolean; locked?: boolean; opacity?: number; center_x?: number; center_y?: number; scale?: number; rotation?: number; position?: number; text?: string; font_size?: number; fill?: string; align?: 'left' | 'center' | 'right'; width?: number; height?: number }
export type LayerCanvasDraft = { layer_id: string; center_x?: number; center_y?: number; scale?: number; sequence: number }
export function layerValues(layer: ImageLayer) {
  return { ...placementOf({ width: layer.width, height: layer.height, layers: [layer] }), opacity: layer.opacity, rotation: ((layer.transform.rotation + 180) % 360 + 360) % 360 - 180 }
}
export async function layerPreview(id: string, revision: number, params: LayerEdit, signal: AbortSignal) {
  const response = await fetch(`/api/sessions/${id}/layers/preview`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, params }), signal })
  if (!response.ok) throw await apiError(response)
  return response.blob()
}
