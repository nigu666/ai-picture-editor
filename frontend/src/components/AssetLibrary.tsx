import { useState, type ChangeEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { assetsApi, type Asset } from '@/api/assets'
import { ApiError } from '@/api/client'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'

const ASSETS_KEY = ['assets']

function AssetCard({ asset, onEdit, onAdd, added, editingBusy }: { asset: Asset; onEdit: () => void; onAdd?: () => void; added?: boolean; editingBusy: boolean }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  return (
    <article className="asset-card">
      <div className="asset-preview">
        {failedUrl === asset.url
          ? <p>预览暂不可用，请刷新素材列表重试。</p>
          : <img src={asset.url} alt={`${asset.source === 'generate' ? '生成' : '上传'}素材，${asset.width}×${asset.height} 像素`} loading="lazy"
            onError={() => setFailedUrl(asset.url)} />}
      </div>
      <div className="asset-card-info">
        <h3>{asset.source === 'generate' ? '生成素材' : '已上传图片'}</h3>
        <p>{asset.image_format} · {asset.width} × {asset.height} · {Math.max(1, Math.round(asset.size_bytes / 1024))} KB</p>
        <button className="secondary asset-edit-button" disabled={editingBusy} onClick={onEdit}>新建编辑会话</button>
        {onAdd && <button className="secondary asset-edit-button" disabled={editingBusy || added} onClick={onAdd}>{added ? '已在当前会话' : '加入当前会话'}</button>}
        <a href={asset.url} target="_blank" rel="noopener noreferrer">查看原图 <span aria-hidden="true">↗</span></a>
      </div>
    </article>
  )
}

export default function AssetLibrary({ userId, onEdit, onAdd, sessionAssetIds, editingBusy }: { userId?: string; onEdit: (asset: Asset) => void; onAdd?: (asset: Asset) => void; sessionAssetIds?: string[]; editingBusy: boolean }) {
  const client = useQueryClient()
  const [localError, setLocalError] = useState('')
  function expireSession(error: unknown) {
    if (error instanceof ApiError && error.status === 401) client.setQueryData(ME_KEY, null)
  }
  const assets = useQuery({
    queryKey: [...ASSETS_KEY, userId],
    enabled: Boolean(userId),
    queryFn: async () => {
      try { return await assetsApi.list() }
      catch (error) { expireSession(error); throw error }
    },
    retry: false,
  })
  const upload = useMutation({
    mutationFn: assetsApi.upload,
    onSuccess: () => client.invalidateQueries({ queryKey: ASSETS_KEY }),
    onError: expireSession,
  })
  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setLocalError('')
    upload.reset()
    if (file.size > 20 * 1024 * 1024) { setLocalError('文件超过 20 MB 上限'); return }
    upload.mutate(file)
  }
  return (
    <section className="asset-library" aria-labelledby="asset-heading">
      <div className="upload-panel">
        <div><h2 id="asset-heading">添加你的图片</h2>
          <p>支持 JPG、PNG、WebP，最大 20 MB，最短边至少 32 像素。</p></div>
        <label className={`primary file-picker ${upload.isPending ? 'is-disabled' : ''}`} htmlFor="asset-file">
          {upload.isPending ? '正在上传…' : '选择图片'}
          <input id="asset-file" type="file" accept=".jpg,.jpeg,.png,.webp" onChange={chooseFile}
            disabled={upload.isPending} aria-label="选择上传图片" />
        </label>
      </div>
      {(localError || upload.isError) && <p className="error-message" role="alert">{localError || errorMessage(upload.error)}</p>}
      {upload.isSuccess && <p className="upload-success" role="status">图片已上传，可以在下方查看。</p>}
      <div className="asset-list-heading"><h2>我的素材</h2>
        <button className="text-button" onClick={() => { void assets.refetch() }} disabled={assets.isFetching}>刷新素材列表</button></div>
      {assets.isPending && <p className="asset-notice" role="status">正在读取素材…</p>}
      {assets.isError && <p className="error-message" role="alert">{errorMessage(assets.error)}，请刷新重试。</p>}
      {!assets.isPending && !assets.isError && assets.data?.length === 0 &&
        <div className="asset-empty"><span aria-hidden="true">＋</span><p>还没有图片，可以上传素材或生成第一组候选。</p></div>}
      {!assets.isError && <div className="asset-grid">{assets.data?.map((asset) => <AssetCard key={asset.id} asset={asset} onEdit={() => onEdit(asset)} onAdd={onAdd ? () => onAdd(asset) : undefined} added={sessionAssetIds?.includes(asset.id)} editingBusy={editingBusy} />)}</div>}
      <p className="asset-stage-note">素材文件保留原样；采用候选、撤销与重做记录在对应编辑会话中。</p>
    </section>
  )
}
