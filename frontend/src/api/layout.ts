import type { CanvasDocument } from './sessions'
import { apiError } from './client'

export type Placement = { center_x: number; center_y: number; scale: number }
export function placementOf(document: CanvasDocument): Placement {
  const layer = document.layers[0], t = layer.transform, radians = t.rotation * Math.PI / 180
  const cos = Math.round(Math.cos(radians) * 1e12) / 1e12, sin = Math.round(Math.sin(radians) * 1e12) / 1e12
  return { center_x: t.x + (cos * t.scale_x * layer.width - sin * t.scale_y * layer.height) / 2,
    center_y: t.y + (sin * t.scale_x * layer.width + cos * t.scale_y * layer.height) / 2, scale: Math.abs(t.scale_x) }
}
export async function layoutPreview(id: string, revision: number, placement: Placement, signal: AbortSignal): Promise<Blob> {
  const response = await fetch(`/api/sessions/${id}/layout-preview`, { method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, placement }), signal })
  if (!response.ok) throw await apiError(response)
  return response.blob()
}
