import { api } from './client'
import type { EditSession } from './sessions'

export type TransformOperation = 'flip_horizontal' | 'flip_vertical' | 'rotate_left' | 'rotate_right'
export const operationLabels: Record<TransformOperation, string> = {
  flip_horizontal: '水平翻转', flip_vertical: '垂直翻转', rotate_left: '左转 90°', rotate_right: '右转 90°',
}
export const cropRatios = ['1:1', '4:5', '3:4', '9:16', '16:9'] as const
export type CropRatio = typeof cropRatios[number]
export type CropBox = { x: number; y: number; width: number; height: number }
export function cropBox(width: number, height: number, ratio: CropRatio): CropBox | null {
  const [a, b] = ratio.split(':').map(Number)
  const n = Math.min(Math.floor(width / a), Math.floor(height / b))
  const w = a * n, h = b * n
  return Math.min(w, h) < 32 ? null : { x: Math.floor((width - w) / 2), y: Math.floor((height - h) / 2), width: w, height: h }
}
export async function canvasTool(id: string, revision: number, tool: string, params: object): Promise<EditSession> {
  const result = await api.post<{ session: EditSession }>(`/sessions/${id}/tools/${tool}`, { revision, params })
  return result.session
}
