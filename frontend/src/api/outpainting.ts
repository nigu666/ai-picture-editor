import { api } from './client'
import type { Run } from './runs'
import type { CropRatio } from './canvas'

export type ExpansionInput = { ratio: CropRatio }
export type ExpansionRun = Run & { request: ExpansionInput }
export const outpaintingApi = {
  options: () => api.get<{ enabled: boolean; model: string }>('/outpainting-options'),
  list: (id: string) => api.get<ExpansionRun[]>(`/sessions/${id}/outpainting-runs`),
  submit: (id: string, revision: number, params: ExpansionInput) => api.post<{ run: Run }>(`/sessions/${id}/tools/expand_canvas`, { revision, params }),
  resume: (id: string, runId: string) => api.post<{ run: Run }>(`/sessions/${id}/outpainting-runs/${runId}/resume`),
}

export function expansionSize(width: number, height: number, ratio: CropRatio) {
  if (Math.min(width, height) < 512 || Math.max(width, height) > 4096) return { error: '当前画布每边需为 512–4096 px，不会自动放大原图。' }
  const [a, b] = ratio.split(':').map(Number), n = Math.max(Math.ceil(width / a), Math.ceil(height / b))
  const w = a * n, h = b * n
  if (w === width && h === height) return { error: '画布已是此比例，无需扩图。' }
  if (Math.max(w, h) > 4096 || w > 2 * width || h > 2 * height) return { error: '目标超出尺寸限制，请选择更接近原图的比例。' }
  return { width: w, height: h }
}
