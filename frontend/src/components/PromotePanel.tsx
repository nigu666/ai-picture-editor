import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { promoteApi, type PromoteProgress } from '@/api/promote'
import { runKey } from '@/api/runs'
import { ApiError } from '@/api/client'
import { useRun } from '@/hooks/useRun'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import type { User } from '@/api/auth'
import type { EditSession } from '@/api/sessions'
import type { SelectionState } from '@/api/selection'

export default function PromotePanel({ row, userId, disabled, draftOpen, selection, onRefresh }: {
  row: EditSession; userId: string; disabled: boolean; draftOpen: boolean; selection?: SelectionState; onRefresh: () => void
}) {
  const { id, revision } = row
  const client = useQueryClient(), lock = useRef(false), retry = useRef<{ fingerprint: string; id: string } | null>(null)
  const [draft, setDraft] = useState<string | null>(null)
  const key = ['promote-runs', userId, id]
  function expire(error: unknown) { if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null) }
  const options = useQuery({ queryKey: ['promote-options', userId], queryFn: async () => { try { return await promoteApi.options() } catch (error) { expire(error); throw error } }, retry: false })
  const list = useQuery({ queryKey: key, queryFn: async () => { try { return await promoteApi.list(id) } catch (error) { expire(error); throw error } }, retry: false, refetchInterval: 5000 })
  const latest = list.data?.[0], task = useRun(userId, latest?.id ?? null)
  const run = (task.display ?? latest) as PromoteProgress | undefined
  const prompt = options.data?.local_repair ? '按原图上下文修复背景' : draft ?? latest?.request.prompt ?? ''
  const active = run?.status === 'queued' || run?.status === 'running'
  const recoverable = run?.status === 'failed' && run.result.recoverable
  const uncertain = run?.status === 'queued' && Boolean(run.error)
  const unknownSubmission = run?.status === 'failed' && run.result.submission_started && !run.result.remote_task_id
  const ready = run?.status === 'succeeded' && Boolean(run.result.layer_document)
  const applied = Boolean(run?.result.applied_revision && JSON.stringify(row.document) === JSON.stringify(run.result.layer_document))
  const stale = Boolean(run && run.result.source_revision !== revision)
  const sameSelection = run?.result.selection_version === selection?.version
  const noNew = active || recoverable || unknownSubmission || (ready && !stale && sameSelection)
  const hasText = row.document.layers.some(layer => layer.kind === 'text')
  const validSelection = Boolean(selection?.has_selection && selection.revision === revision)
  const validSize = Math.min(row.document.width, row.document.height) >= 512 && Math.max(row.document.width, row.document.height) <= 4096
  const mutation = useMutation({ mutationFn: async (resume: boolean) => {
    await client.cancelQueries({ queryKey: key })
    if (latest) await client.cancelQueries({ queryKey: runKey(userId, latest.id) })
    if (resume && latest) return promoteApi.resume(id, latest.id)
    const fingerprint = JSON.stringify([revision, selection?.version, prompt.trim()])
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, id: crypto.randomUUID() }
    return promoteApi.submit(id, revision, { prompt: prompt.trim(), selection_version: selection!.version, request_id: retry.current.id })
  }, retry: false, onSuccess: ({ run }) => {
    client.setQueryData(runKey(userId, run.id), run); void client.invalidateQueries({ queryKey: key }); retry.current = null
  }, onError: error => { expire(error); void list.refetch(); if (error instanceof ApiError && error.status === 409) onRefresh() }, onSettled: () => { lock.current = false } })
  const apply = useMutation({ mutationFn: () => promoteApi.apply(id, latest!.id, revision), retry: false,
    onSuccess: row => { client.setQueryData(['edit-session', userId, id], row); void client.invalidateQueries({ queryKey: ['sessions', userId] }); void list.refetch(); if (latest) void task.snapshot.refetch(); onRefresh() },
    onError: error => { expire(error); onRefresh(); void list.refetch(); if (latest) void task.snapshot.refetch() } })
  const blocked = disabled || mutation.isPending || apply.isPending || list.isPending || list.isError || options.isError || !options.data?.enabled
  function submit(resume: boolean) {
    if (lock.current || blocked || (resume ? !(recoverable || uncertain) : hasText || noNew || draftOpen || !validSelection || !validSize || row.document.layers.length > 18 || prompt.trim().length < 2)) return
    lock.current = true; mutation.mutate(resume)
  }
  const { isError: submissionFailed, reset: resetSubmission } = mutation
  const { isError: applyFailed, reset: resetApply } = apply
  useEffect(() => { if (applyFailed && applied) resetApply() }, [applyFailed, applied, resetApply])
  useEffect(() => { if (task.terminal) { void client.invalidateQueries({ queryKey: ['edit-session', userId, id] }); void client.invalidateQueries({ queryKey: ['promote-runs', userId, id] }) } }, [task.terminal, latest?.id, client, userId, id])
  useEffect(() => { if (submissionFailed && latest?.request.request_id === retry.current?.id) { retry.current = null; resetSubmission() } }, [submissionFailed, latest?.request.request_id, resetSubmission])
  const previews = task.candidates.filter(asset => asset.id === run?.result.object_asset_id || asset.id === run?.result.background_asset_id)
  return <details className="background-panel promote-panel" open={Boolean(run)} data-promote-run={run?.id} data-promote-status={run?.status}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4M8 8h8v8H8z"/></svg>选区成层</span><span className="background-badge">选中物体独立调整</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body">
      <p className="background-intro">先用笔刷或智能点选选中物体，再裁出透明图层并补全原位置。检查结果后才应用，原图和现有历史保留。</p>
      {!validSelection && <p className="background-note">请先在上方建立非空选区。</p>}
      {hasText && <p className="background-note">含可编辑文字层时暂不支持选区成层；请在添加文字前完成物体成层。</p>}
      {!validSize && <p className="background-note">画布每边需在512～4096 px之间。</p>}
      {row.document.layers.length > 18 && <p className="background-note">现有图层最多18层，需预留背景修复与物体图层的位置。</p>}
      {options.data && !options.data.enabled && <p className="background-note">请先准备本地背景修复模型；云端模式还需配置百炼。</p>}
      <p className="background-note">{options.data?.local_repair ? '按周围图像结构进行本地补洞，无法凭文字指定新场景。大面积遮挡处的细节可能偏平滑，请检查后应用。' : '只描述补全后的背景材质、颜色与光线；移除范围由选区决定，描述中请去掉“删除、移除、不要”等动作或否定句。大范围遮挡的补全可能出现结构偏差，请检查后再应用。'}</p>
      <form onSubmit={event => { event.preventDefault(); submit(false) }}>{!options.data?.local_repair && <><label htmlFor={`promote-prompt-${id}`}>物体移开后，原位置的背景应该是什么样</label>
        <textarea id={`promote-prompt-${id}`} maxLength={600} value={prompt} disabled={blocked || Boolean(noNew)} placeholder="例如：连续的浅色木纹桌面，柔和自然光，光影与周围一致" onChange={event => setDraft(event.target.value)}/>
        </>}
        <div className="background-form-footer"><span className="background-note">{options.data?.local_repair ? '本地补洞 · 不产生云端生成费' : `${prompt.length}/600 · 背景补全按张计费`}</span><button className="primary background-submit" type="submit" disabled={blocked || hasText || Boolean(noNew) || draftOpen || !validSelection || !validSize || row.document.layers.length > 18 || prompt.trim().length < 2}>{mutation.isPending ? '正在提交…' : active ? '正在生成成层结果…' : '生成独立物体与背景'}</button></div>
      </form>
      <p className="background-note">需完整不透明背景；抠取范围取决于选区，补全内容需人工检查。</p>
      {draftOpen && <p className="background-note">先应用或取消当前预览，再提交成层。</p>}
      {unknownSubmission && <p className="background-note">百炼提交未确认，请先核对平台记录，不重复生成。</p>}
      {run && <div className={`background-status status-${run.status}`} role="status"><div><span>{ready ? '物体与背景结果已保存' : run.status === 'failed' ? '选区成层未完成' : run.stage}</span><span>{run.progress}%</span></div><progress aria-label="选区成层进度" value={run.progress} max={100}/><p>基于修订 {run.result.source_revision}、选区版本 {run.result.selection_version}。{stale && !applied ? '当前画布已有更新，结果保留为独立素材。' : '生成完成也不会自动修改画布。'}</p>{run.error && <p className="error-message" role="alert">{run.error}</p>}{(recoverable || uncertain) && <button className="secondary" type="button" disabled={blocked} onClick={() => submit(true)}>继续原成层任务</button>}</div>}
      {ready && <div className="split-result"><div className="split-thumbnails">{previews.map(asset => <figure key={asset.id}><img src={asset.url} alt={asset.id === run?.result.object_asset_id ? '独立物体预览' : '原位置背景修复预览'}/><figcaption>{asset.id === run?.result.object_asset_id ? '独立物体' : '背景修复'}</figcaption></figure>)}</div><p className="background-note">请先检查物体边缘与背景。应用后可在右侧选择“独立物体”移动、缩放或隐藏，可撤销。</p><button className="primary" type="button" disabled={blocked || draftOpen || stale || applied} onClick={() => apply.mutate()}>{apply.isPending ? '正在应用…' : applied ? '已应用成层结果' : '应用成层结果'}</button></div>}
      {(options.isError || list.isError || task.snapshot.isError || mutation.isError || apply.isError) && <p className="error-message" role="alert">{errorMessage(apply.error ?? mutation.error ?? options.error ?? list.error ?? task.snapshot.error)}；请刷新原任务核对。</p>}
      <div className="background-refresh"><span>{task.reconnecting ? '实时连接暂断，正在查询进度。' : '先生成素材，明确应用后才修改图层。'}</span><button className="text-button" type="button" disabled={list.isFetching || mutation.isPending || apply.isPending} onClick={() => { void options.refetch(); void list.refetch(); if (latest) void task.snapshot.refetch() }}>刷新成层任务</button></div>
    </div>
  </details>
}
