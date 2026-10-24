import { api } from './client'
import type { EditSession } from './sessions'

export type TextInput = { text: string; x: number; y: number; width: number; height: number; font_size: number; fill: string }
export type OcrBox = Omit<TextInput, 'fill'> & { id: string; confidence: number }
export type OcrResult = { revision: number; provider: string; boxes: OcrBox[]; truncated: boolean }
export type AddText = { revision: number; request_id: string; layers: TextInput[] }
export const textApi = {
  options: (id: string) => api.get<{ ocr_enabled: boolean; text_enabled: boolean; font_name: string; provider: string }>(`/sessions/${id}/text-options`),
  recognize: (id: string, revision: number) => api.post<OcrResult>(`/sessions/${id}/ocr`, { revision }),
  add: (id: string, body: AddText) => api.post<EditSession>(`/sessions/${id}/text-layers`, body),
  remove: (id: string, layer: string, revision: number) => api.post<EditSession>(`/sessions/${id}/text-layers/${encodeURIComponent(layer)}/remove`, { revision }),
}
