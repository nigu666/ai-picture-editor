import { apiError } from './client'

export type ColorSettings = {
  brightness: number; contrast: number; saturation: number; sharpness: number
  highlights: number; shadows: number; temperature: number; tint: number
  vibrance: number; clarity: number; vignette: number
}
export const neutralColors: ColorSettings = { brightness: 1, contrast: 1, saturation: 1, sharpness: 1, highlights: 0, shadows: 0, temperature: 0, tint: 0, vibrance: 0, clarity: 0, vignette: 0 }
export const normalizeColors = (saved: Partial<ColorSettings> = {}): ColorSettings => ({ ...neutralColors, ...saved })
export type ColorControl = { name: keyof ColorSettings; label: string; min: number; max: number; left: string; right: string; offset?: boolean }
export const basicColors: ColorControl[] = [
  { name: 'brightness', label: '亮度', min: 0, max: 200, left: '0%', right: '200%' },
  { name: 'contrast', label: '对比度', min: 0, max: 200, left: '0%', right: '200%' },
  { name: 'saturation', label: '饱和度', min: 0, max: 200, left: '0%', right: '200%' },
]
export const toneColors: ColorControl[] = [
  { name: 'highlights', label: '高光', min: -100, max: 100, left: '压暗亮部', right: '提亮亮部', offset: true },
  { name: 'shadows', label: '阴影', min: -100, max: 100, left: '加深暗部', right: '提亮暗部', offset: true },
]
export const balanceColors: ColorControl[] = [
  { name: 'temperature', label: '色温', min: -100, max: 100, left: '偏冷', right: '偏暖', offset: true },
  { name: 'tint', label: '色调', min: -100, max: 100, left: '偏绿', right: '偏洋红', offset: true },
]
export const expressionColors: ColorControl[] = [{ name: 'vibrance', label: '自然饱和度', min: -100, max: 100, left: '柔和色彩', right: '增强淡色', offset: true }]
export const detailColors: ColorControl[] = [
  { name: 'sharpness', label: '锐化', min: 0, max: 200, left: '柔和 · 0%', right: '清晰 · 200%' },
  { name: 'clarity', label: '清晰度', min: -100, max: 100, left: '柔化质感', right: '增强质感', offset: true },
]
export const finishColors: ColorControl[] = [{ name: 'vignette', label: '暗角', min: 0, max: 100, left: '无暗角', right: '边缘渐暗', offset: true }]
export const advancedColorControls = [...toneColors, ...balanceColors, ...expressionColors, ...detailColors, ...finishColors]
export const allColorControls = [...basicColors, ...advancedColorControls]
export function colorValue(control: ColorControl, value: number) {
  const amount = Math.round(value * 100)
  return control.offset ? `${amount > 0 ? '+' : ''}${amount}` : `${amount}%`
}
export function colorSourceUrl(id: string, revision: number, previous = false) {
  return `/api/sessions/${encodeURIComponent(id)}/color-source?revision=${revision}&previous=${previous}`
}
export async function colorPreview(id: string, revision: number, adjustments: ColorSettings, signal: AbortSignal) {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/color-preview`, {
    method: 'POST', credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, adjustments }),
  })
  if (!response.ok) throw await apiError(response)
  return response.blob()
}
