import { api, apiError } from './client'

export type Asset = {
  id: string
  kind: 'original' | 'generated' | 'subject' | 'background' | 'mask' | 'marketing' | 'export'
  source: 'upload' | 'generate' | 'tool'
  image_format: string
  width: number
  height: number
  size_bytes: number
  created_at: string
  url: string
}

export const assetsApi = {
  get: (id: string) => api.get<Asset>(`/assets/${encodeURIComponent(id)}`),
  list: () => api.get<Asset[]>('/assets'),
  upload: async (file: File): Promise<Asset> => {
    const body = new FormData()
    body.append('file', file)
    // FormData 的 Content-Type 和 boundary 由浏览器生成，不使用 JSON 请求头。
    const response = await fetch('/api/assets', { method: 'POST', body, credentials: 'same-origin' })
    if (!response.ok) throw await apiError(response)
    return response.json()
  },
}
