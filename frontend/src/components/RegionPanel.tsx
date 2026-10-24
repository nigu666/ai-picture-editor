import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { regionApi, type RegionKind } from '@/api/region'
import { runKey } from '@/api/runs'
import type { SelectionState } from '@/api/selection'
import { useRun } from '@/hooks/useRun'
import { ApiError } from '@/api/client'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import type { User } from '@/api/auth'

export default function RegionPanel({ id, revision, width, height, userId, disabled, draftOpen, selection, onRefresh }: {
  id: string; revision: number; width: number; height: number; userId: string; disabled: boolean; draftOpen: boolean; selection?: SelectionState; onRefresh: () => void
}) {
  const client = useQueryClient(), lock = useRef(false), retry = useRef<{ fingerprint: string; id: string } | null>(null)
  const [draftKind, setKind] = useState<RegionKind | null>(null), [draftPrompt, setPrompt] = useState<string | null>(null)
  const key = ['region-runs', userId, id]
  function expire(error: unknown) { if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null) }
  const options = useQuery({ queryKey: ['region-options', userId], queryFn: async () => { try { return await regionApi.options() } catch (error) { expire(error); throw error } }, retry: false })
  const list = useQuery({ queryKey: key, queryFn: async () => { try { return await regionApi.list(id) } catch (error) { expire(error); throw error } }, retry: false, refetchInterval: 5000 })
  const latest = list.data?.[0], task = useRun(userId, latest?.id ?? null), run = task.display ?? latest
  const kind = draftKind ?? (latest?.tool === 'replace_region' ? 'replace_region' : 'erase_region')
  const prompt = draftPrompt ?? latest?.request.prompt ?? ''
  const active = run?.status === 'queued' || run?.status === 'running'
  const recoverable = run?.status === 'failed' && run.result.recoverable && Boolean(run.result.remote_task_id)
  const uncertain = run?.status === 'queued' && Boolean(run.error)
  const mutation = useMutation({ mutationFn: async (resume: boolean) => {
    if (latest) await client.cancelQueries({ queryKey: runKey(userId, latest.id) })
    await client.cancelQueries({ queryKey: key })
    if (resume && latest) return regionApi.resume(id, latest.id)
    const fingerprint = JSON.stringify([revision, selection?.version, kind, prompt.trim()])
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, id: crypto.randomUUID() }
    return regionApi.submit(id, revision, kind, { prompt: prompt.trim(), selection_version: selection!.version, request_id: retry.current.id })
  }, retry: false, onSuccess: ({ run }) => {
    client.setQueryData(runKey(userId, run.id), run)
    void client.invalidateQueries({ queryKey: key })
    retry.current = null
  }, onError: error => { expire(error); void list.refetch(); if (error instanceof ApiError && error.status === 409) onRefresh() }, onSettled: () => { lock.current = false } })
  const blocked = disabled || mutation.isPending || list.isPending || list.isError || options.isError || !options.data?.enabled
  const validSize = Math.min(width, height) >= 512 && Math.max(width, height) <= 4096
  const validSelection = Boolean(selection?.has_selection && selection.revision === revision)
  const { isError: submissionFailed, reset: resetSubmission } = mutation
  function submit(resume: boolean) {
    if (lock.current || blocked || (resume ? !(recoverable || uncertain) : active || recoverable || draftOpen || !validSelection || !validSize || kind === 'replace_region' && !prompt.trim())) return
    lock.current = true; mutation.mutate(resume)
  }
  useEffect(() => { if (task.terminal) void client.invalidateQueries({ queryKey: ['edit-session', userId, id] }) }, [task.terminal, latest?.id, client, userId, id])
  useEffect(() => {
    if (submissionFailed && latest?.request.request_id === retry.current?.id) { retry.current = null; resetSubmission() }
  }, [latest?.request.request_id, submissionFailed, resetSubmission])
  return <details className="background-panel region-panel" open={Boolean(run)} data-region-run={run?.id} data-region-status={run?.status}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 3H3v4m16-4h2v4M3 17v4h4m14-4v4h-4M8 15l7-7 3 3-7 7H8v-3Z"/></svg>局部编辑</span><span className="background-badge">只修改选中区域</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body">
      <p className="background-intro">先在上方选择区域，再消除或替换。提交时固定选区，生成一张候选后再采用。</p>
      {!validSelection && <p className="background-note" role="status">尚未选择区域，请先用笔刷或智能点选建立选区。</p>}
      {!validSize && <p className="background-note">画布每边需在 512～4096 px 之间。</p>}
      {options.data && !options.data.enabled && <p className="background-note">局部编辑尚未配置百炼密钥或未启用。</p>}
      <form onSubmit={event => { event.preventDefault(); submit(false) }}>
        <div className="region-modes" role="group" aria-label="局部编辑方式"><button className="secondary" type="button" aria-pressed={kind === 'erase_region'} disabled={blocked || active || Boolean(recoverable)} onClick={() => { setKind('erase_region'); setPrompt('') }}>局部消除</button><button className="secondary" type="button" aria-pressed={kind === 'replace_region'} disabled={blocked || active || Boolean(recoverable)} onClick={() => { setKind('replace_region'); setPrompt('') }}>局部替换</button></div>
        <label htmlFor={`region-prompt-${id}`}>{kind === 'erase_region' ? '删除后应出现的背景（可留空）' : '替换内容描述'}</label>
        <textarea id={`region-prompt-${id}`} maxLength={800} value={prompt} disabled={blocked || active || Boolean(recoverable)} placeholder={kind === 'erase_region' ? '小物体可留空；较大物体请描述补全后的背景，例如：干净的浅色墙面' : '例如：把选中的花瓶替换为一个蓝色陶瓷花瓶'} onChange={event => setPrompt(event.target.value)}/>
        <div className="background-form-footer"><span className="background-note">{validSelection ? `当前选区版本 ${selection?.version}` : '等待建立选区'} · {prompt.length}/800</span><button type="submit" className="primary background-submit" disabled={blocked || active || Boolean(recoverable) || draftOpen || !validSelection || !validSize || kind === 'replace_region' && !prompt.trim()}>{mutation.isPending ? '正在提交…' : active ? '正在生成局部候选…' : kind === 'erase_region' ? '生成消除候选' : '生成替换候选'}</button></div>
      </form>
      <p className="background-note">调用百炼万相，按张计费。当前支持不透明画布；选区外像素保持原样，边缘质量请对比后确认。</p>
      {draftOpen && <p className="background-note">先应用或取消当前预览，再提交局部编辑。</p>}
      {run && <div className={`background-status status-${run.status}`} role="status"><div><span>{run.status === 'succeeded' ? '局部编辑候选已保存，请在会话候选中查看' : run.status === 'failed' ? '局部编辑未完成' : run.stage}</span><span>{run.progress}%</span></div><progress aria-label="局部编辑进度" value={run.progress} max={100}/><p>使用修订 {run.result.source_revision}、选区版本 {run.result.selection_version} 的固定快照{run.result.source_revision !== revision ? '；当前画布已有更新，结果保留为独立候选。' : '。'}</p>{run.error && <p className="error-message" role="alert">{run.error}</p>}{(recoverable || uncertain) && <button className="secondary" type="button" disabled={blocked} onClick={() => submit(true)}>{recoverable ? '继续查询原局部任务' : '重新投递同一局部任务'}</button>}</div>}
      {(options.isError || list.isError || task.snapshot.isError || mutation.isError) && <p className="error-message" role="alert">{errorMessage(mutation.error ?? options.error ?? list.error ?? task.snapshot.error)}；请先刷新局部任务核对。</p>}
      <div className="background-refresh"><span>{task.reconnecting ? '实时连接暂断，正在查询进度。' : '采用前原画布不变，采用后可撤销。'}</span><button className="text-button" type="button" disabled={list.isFetching || mutation.isPending} onClick={() => { void options.refetch(); void list.refetch(); if (latest) void task.snapshot.refetch() }}>刷新局部任务</button></div>
    </div>
  </details>
}
