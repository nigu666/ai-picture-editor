import { ApiError, apiError } from './client'

export type ExportOptions = { format: 'png' | 'jpeg'; jpeg_quality: number; background: string }
export const deliverySizes = {
  '1:1': [1080, 1080], '4:5': [1080, 1350], '3:4': [1080, 1440], '9:16': [1080, 1920], '16:9': [1920, 1080],
} as const
export type DeliveryRatio = keyof typeof deliverySizes
export type BundleOptions = { ratios: DeliveryRatio[]; include_original: boolean; allow_upscale: boolean }

export async function exportCanvas(id: string, revision: number, options: ExportOptions, signal: AbortSignal, bundle?: BundleOptions) {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/${bundle ? 'export-bundle' : 'export'}`, {
    method: 'POST', credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, ...options, ...bundle }),
  })
  if (!response.ok) throw await apiError(response)
  const type = bundle ? 'application/zip' : options.format === 'png' ? 'image/png' : 'image/jpeg'
  if (response.headers.get('X-Canvas-Revision') !== String(revision)) throw new ApiError(409, '导出版本不一致，请重新读取会话')
  if (response.headers.get('Content-Type')?.split(';')[0] !== type) throw new Error('导出文件类型不符，请重试')
  if (bundle && response.headers.get('X-Export-File-Count') !== String(bundle.ratios.length + Number(bundle.include_original))) throw new Error('导出文件数量不符，请重试')
  const extension = bundle ? 'zip' : options.format === 'png' ? 'png' : 'jpg'
  const encoded = response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const filename = encoded ? decodeURIComponent(encoded) : `画布-r${revision}.${extension}`
  return { blob: await response.blob(), filename }
}
