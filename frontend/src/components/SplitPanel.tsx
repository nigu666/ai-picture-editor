import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { splitApi, type SplitProgress } from '@/api/split'
import { runKey } from '@/api/runs'
import { ApiError } from '@/api/client'
import { useRun } from '@/hooks/useRun'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import type { User } from '@/api/auth'
import type { CanvasDocument } from '@/api/sessions'

export default function SplitPanel({ id, revision, width, height, userId, disabled, draftOpen, single, currentDocument, onRefresh }: {
  id: string; revision: number; width: number; height: number; userId: string; disabled: boolean; draftOpen: boolean; single: boolean; currentDocument: CanvasDocument; onRefresh: () => void
}) {
  const client = useQueryClient(), lock = useRef(false), retry = useRef<{ fingerprint: string; id: string } | null>(null)
  const [draft, setDraft] = useState<string | null>(null)
  const key = ['split-runs', userId, id]
  function expire(error: unknown) { if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null) }
  const options = useQuery({ queryKey: ['split-options', userId], queryFn: async () => { try { return await splitApi.options() } catch (error) { expire(error); throw error } }, retry: false })
  const list = useQuery({ queryKey: key, queryFn: async () => { try { return await splitApi.list(id) } catch (error) { expire(error); throw error } }, retry: false, refetchInterval: 5000 })
  const latest = list.data?.[0], task = useRun(userId, latest?.id ?? null)
  const run = (task.display ?? latest) as SplitProgress | undefined
  const prompt = options.data?.local_repair ? '按原图上下文修复背景' : draft ?? latest?.request.prompt ?? ''
  const active = run?.status === 'queued' || run?.status === 'running'
  const recoverable = run?.status === 'failed' && run.result.recoverable
  const uncertain = run?.status === 'queued' && Boolean(run.error)
  const unknownSubmission = run?.status === 'failed' && run.result.submission_started && !run.result.remote_task_id
  const stale = Boolean(run && run.result.source_revision !== revision)
  const applied = Boolean(run?.result.applied_revision && JSON.stringify(currentDocument) === JSON.stringify(run.result.layer_document))
  const ready = run?.status === 'succeeded' && Boolean(run.result.layer_document)
  const validSize = Math.min(width, height) >= 512 && Math.max(width, height) <= 4096
  const mutation = useMutation({ mutationFn: async (resume: boolean) => {
    await client.cancelQueries({ queryKey: key })
    if (latest) await client.cancelQueries({ queryKey: runKey(userId, latest.id) })
    if (resume && latest) return splitApi.resume(id, latest.id)
    const fingerprint = JSON.stringify([revision, prompt.trim()])
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, id: crypto.randomUUID() }
    return splitApi.submit(id, revision, { prompt: prompt.trim(), request_id: retry.current.id })
  }, retry: false, onSuccess: ({ run }) => {
    client.setQueryData(runKey(userId, run.id), run)
    void client.invalidateQueries({ queryKey: key }); retry.current = null
  }, onError: error => { expire(error); void list.refetch(); if (error instanceof ApiError && error.status === 409) onRefresh() }, onSettled: () => { lock.current = false } })
  const apply = useMutation({ mutationFn: () => splitApi.apply(id, latest!.id, revision), retry: false,
    onSuccess: row => { client.setQueryData(['edit-session', userId, id], row); void list.refetch(); if (latest) void task.snapshot.refetch(); onRefresh() },
    onError: error => { expire(error); onRefresh(); void list.refetch(); if (latest) void task.snapshot.refetch() } })
  const blocked = disabled || mutation.isPending || apply.isPending || list.isPending || list.isError || options.isError || !options.data?.enabled
  const noNew = active || recoverable || unknownSubmission || (ready && !stale)
  function submit(resume: boolean) {
    if (lock.current || blocked || (resume ? !(recoverable || uncertain) : noNew || draftOpen || !single || !validSize || prompt.trim().length < 2)) return
    lock.current = true; mutation.mutate(resume)
  }
  const { isError: submissionFailed, reset: resetSubmission } = mutation
  const { isError: applyFailed, reset: resetApply } = apply
  useEffect(() => { if (applyFailed && applied) resetApply() }, [applyFailed, applied, resetApply])
  useEffect(() => { if (task.terminal) { void client.invalidateQueries({ queryKey: ['edit-session', userId, id] }); void client.invalidateQueries({ queryKey: key }) } }, [task.terminal, latest?.id, client, userId, id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (submissionFailed && latest?.request.request_id === retry.current?.id) { retry.current = null; resetSubmission() } }, [submissionFailed, latest?.request.request_id, resetSubmission])
  return <details className="background-panel split-panel" open={Boolean(run)} data-split-run={run?.id} data-split-status={run?.status}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true"><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/></svg>主体与背景拆层</span><span className="background-badge">检查后应用</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body">
      <p className="background-intro">本地抠出透明主体，再补全被遮挡的背景，生成两张独立素材。适合主体边界清晰、背景完整的照片。</p>
      {!single && <p className="background-note">当前已有多个图层，无需重复拆层。</p>}
      {!validSize && <p className="background-note">画布每边需在 512～4096 px 之间。</p>}
      {options.data && !options.data.enabled && <p className="background-note">请先准备背景修复与本地抠图模型；云端模式还需配置百炼。</p>}
      <p className="background-note">{options.data?.local_repair ? '按周围图像结构进行本地补洞，无法凭文字指定新场景。大面积遮挡处的细节可能偏平滑，请检查后应用。' : '只描述补全后的背景材质、颜色与光线，避免删除动作或否定句；请检查后应用。'}</p>
      <form onSubmit={event => { event.preventDefault(); submit(false) }}>
        {!options.data?.local_repair && <><label htmlFor={`split-prompt-${id}`}>主体移开后，背景应该是什么样</label>
        <textarea id={`split-prompt-${id}`} maxLength={600} value={prompt} disabled={blocked || Boolean(noNew) || !single} placeholder="例如：浅灰墙面、连续木纹地板、柔和侧光。只写背景材质与光线" onChange={event => setDraft(event.target.value)}/></>}
        <div className="background-form-footer"><span className="background-note">{options.data?.local_repair ? '本地补洞 · 不产生云端生成费' : `${prompt.length}/600 · 背景补全按张计费`}</span><button className="primary background-submit" type="submit" disabled={blocked || Boolean(noNew) || draftOpen || !single || !validSize || prompt.trim().length < 2}>{mutation.isPending ? '正在提交…' : active ? '正在分离与补全…' : '生成主体与背景'}</button></div>
      </form>
      {draftOpen && <p className="background-note">先应用或取消当前预览，再拆层。</p>}
      {unknownSubmission && <p className="background-note">百炼提交结果未确认，请先到平台核对调用记录，暂不重复生成。</p>}
      {run && <div className={`background-status status-${run.status}`} role="status"><div><span>{ready ? '主体与背景已保存' : run.status === 'failed' ? '拆层未完成' : run.stage}</span><span>{run.progress}%</span></div><progress aria-label="主体与背景拆层进度" value={run.progress} max={100}/><p>基于修订 {run.result.source_revision} 的固定画布。{stale && !applied ? '当前画布已有更新，结果仍保留为独立素材。' : '原图始终保留。'}</p>{run.error && <p className="error-message" role="alert">{run.error}</p>}{(recoverable || uncertain) && <button className="secondary" type="button" disabled={blocked} onClick={() => submit(true)}>继续原拆层任务</button>}</div>}
      {ready && <div className="split-result"><div className="split-thumbnails">{task.candidates.map(asset => <figure key={asset.id}><img src={asset.url} alt={asset.kind === 'subject' ? '透明主体预览' : '补全背景预览'}/><figcaption>{asset.kind === 'subject' ? '透明主体' : '补全背景'}</figcaption></figure>)}</div><p className="background-note">请检查主体边缘和背景补全；应用后将建立“背景＋主体”两层，可撤销。背景补全质量受原图影响。</p><button className="primary" type="button" disabled={blocked || draftOpen || stale || applied || !single} onClick={() => apply.mutate()}>{apply.isPending ? '正在应用…' : applied ? '已应用拆层结果' : '应用拆层结果'}</button></div>}
      {(options.isError || list.isError || task.snapshot.isError || mutation.isError || apply.isError) && <p className="error-message" role="alert">{errorMessage(apply.error ?? mutation.error ?? options.error ?? list.error ?? task.snapshot.error)}；请刷新任务与会话核对。</p>}
      <div className="background-refresh"><span>{task.reconnecting ? '实时连接暂断，正在查询进度。' : '生成两张素材，点击应用后才修改画布。'}</span><button className="text-button" type="button" disabled={list.isFetching || mutation.isPending || apply.isPending} onClick={() => { void options.refetch(); void list.refetch(); if (latest) void task.snapshot.refetch() }}>刷新拆层任务</button></div>
    </div>
  </details>
}
