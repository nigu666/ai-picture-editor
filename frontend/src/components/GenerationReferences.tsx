import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { assetsApi, type Asset } from '@/api/assets'
import { ApiError } from '@/api/client'
import type { User } from '@/api/auth'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'

export default function GenerationReferences({ userId, selected, onChange, onValidityChange, enabled, disabled, maxImages, minSide, maxSide, maxBytes }: {
  userId: string; selected: string[]; onChange: (ids: string[]) => void; onValidityChange: (value: boolean) => void
  enabled: boolean; disabled: boolean; maxImages: number; minSide: number; maxSide: number; maxBytes: number
}) {
  const client = useQueryClient()
  const [failedUrls, setFailedUrls] = useState<string[]>([])
  function expire(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
  }
  const available = useQuery({ queryKey: ['assets', userId], enabled, retry: false, queryFn: async () => {
    try { return await assetsApi.list() } catch (error) { expire(error); throw error }
  } })
  const details = useQuery({ queryKey: ['generation-reference-selection', userId, selected], enabled: selected.length > 0, retry: false,
    queryFn: () => Promise.all(selected.map(async (id) => {
      try { return await assetsApi.get(id) } catch (error) {
        expire(error)
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    })),
  })
  function issue(asset: Asset): string {
    if (asset.size_bytes > maxBytes) return '超过10MB'
    if (Math.min(asset.width, asset.height) < minSide || Math.max(asset.width, asset.height) > maxSide) return '尺寸不符合'
    if (!['JPEG', 'PNG', 'WEBP'].includes(asset.image_format)) return '格式不支持'
    return ''
  }
  const valid = selected.length === 0 || (enabled && selected.length <= maxImages && !details.isPending && !details.isError
    && details.data?.length === selected.length && details.data.every((asset) => asset !== null && !issue(asset)))
  useEffect(() => { onValidityChange(Boolean(valid)) }, [onValidityChange, valid])

  function refresh() { void available.refetch(); if (selected.length) void details.refetch() }
  return <details className="generation-references" open={selected.length > 0}>
    <summary>参考图（可选）{selected.length ? ` · 已选${selected.length}张` : ''}</summary>
    <p className="generation-help">按选择顺序编号，可在描述里写“图1”“图2”。最多{maxImages}张，每边{minSide}～{maxSide}px、单张不超过10MB。选中的原图将发送给百炼，生成结果需要手动采用。</p>
    {!enabled && <p className="connection-notice">参考图生成尚未启用；可清空参考图后使用纯文字生图。</p>}
    <ol className="generation-selected-references">
      {selected.map((id, index) => {
        const asset = details.data?.find((item) => item?.id === id)
        return <li key={id}>
          {asset && !failedUrls.includes(asset.url) ? <img src={asset.url} alt={`已选参考图${index + 1}`} onError={() => setFailedUrls((previous) => [...previous, asset.url])} /> : <span className="reference-placeholder">{details.isPending ? '读取中' : '预览不可用'}</span>}
          <div><strong>图{index + 1}</strong><p className="generation-help">{asset ? `${asset.width} × ${asset.height}${issue(asset) ? ` · ${issue(asset)}` : ''}` : details.isPending ? '正在核对素材' : '素材不可用，请移除后重选'}</p></div>
          <button className="text-button" type="button" disabled={disabled} onClick={() => onChange(selected.filter((value) => value !== id))}>移除</button>
        </li>
      })}
    </ol>
    {enabled && <>
      <p className="generation-help">从最近50份素材中选择；需要新图片时，可先在下方“我的素材”上传，再刷新这里。</p>
      {available.isPending && <p role="status" className="generation-help">正在读取素材…</p>}
      {available.data?.length === 0 && <p className="generation-help">暂无素材，请先上传图片。</p>}
      <div className="generation-reference-library">
        {available.data?.map((asset) => {
          const chosen = selected.includes(asset.id), problem = issue(asset)
          return <button key={asset.id} className={`generation-reference-choice ${chosen ? 'is-selected' : ''}`} type="button"
            aria-pressed={chosen} aria-label={`${chosen ? '取消' : '选择'}参考素材，${asset.width}乘${asset.height}${problem ? `，${problem}` : ''}`}
            disabled={disabled || (!chosen && (Boolean(problem) || selected.length >= maxImages))}
            onClick={() => onChange(chosen ? selected.filter((id) => id !== asset.id) : [...selected, asset.id])}>
            {!failedUrls.includes(asset.url) ? <img loading="lazy" src={asset.url} alt="参考素材预览" onError={() => setFailedUrls((previous) => [...previous, asset.url])} /> : <span className="reference-placeholder">预览不可用</span>}
            <span>{chosen ? `图${selected.indexOf(asset.id) + 1}` : problem || `${asset.width} × ${asset.height}`}</span>
          </button>
        })}
      </div>
    </>}
    {(available.isError || details.isError) && <p className="error-message" role="alert">{errorMessage(details.error ?? available.error)}</p>}
    <div className="generation-record-actions"><button className="text-button" type="button" disabled={disabled || available.isFetching || details.isFetching} onClick={refresh}>刷新参考素材</button>
      {selected.length > 0 && <button className="text-button" type="button" disabled={disabled} onClick={() => onChange([])}>清空参考图</button>}</div>
  </details>
}
