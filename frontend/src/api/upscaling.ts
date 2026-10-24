import { api } from './client'
import type { Run } from './runs'

export type UpscaleInput = { scale: 2 | 4 }
export type UpscaleRun = Run & { request: UpscaleInput }
export const upscalingApi = {
  options: () => api.get<{ enabled: boolean; model: string }>('/upscaling-options'),
  list: (id: string) => api.get<UpscaleRun[]>(`/sessions/${id}/upscaling-runs`),
  submit: (id: string, revision: number, params: UpscaleInput) => api.post<{ run: Run }>(`/sessions/${id}/tools/upscale_image`, { revision, params }),
  resume: (id: string, runId: string) => api.post<{ run: Run }>(`/sessions/${id}/upscaling-runs/${runId}/resume`),
}

export function upscaleSize(width: number, height: number, scale: 2 | 4) {
  if (Math.min(width, height) < 512) return { error: '当前画布每边至少需 512 px，不会先插值放大原图。' }
  const w = width * scale, h = height * scale
  if (Math.max(w, h) > 4096) return { error: '输出每边最多 4096 px，请降低倍率或选择较小画布。' }
  return { width: w, height: h }
}
