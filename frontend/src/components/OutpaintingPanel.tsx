import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { cropRatios, type CropRatio } from '@/api/canvas'
import { outpaintingApi, expansionSize, type ExpansionRun } from '@/api/outpainting'
import { runKey } from '@/api/runs'
import { useRun } from '@/hooks/useRun'
import { ApiError } from '@/api/client'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import type { User } from '@/api/auth'

export default function OutpaintingPanel({ id, revision, width, height, userId, disabled, draftOpen, onRefresh }: {
  id: string; revision: number; width: number; height: number; userId: string
  disabled: boolean; draftOpen: boolean; onRefresh: () => unknown
}) {
  const client = useQueryClient(), lock = useRef(false)
  const [draft, setDraft] = useState<CropRatio | null>(null)
  const key = ['outpainting-runs', userId, id]
  function expire(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
  }
  const options = useQuery({ queryKey: ['outpainting-options', userId], queryFn: async () => { try { return await outpaintingApi.options() } catch (error) { expire(error); throw error } }, retry: false })
  const list = useQuery({ queryKey: key, queryFn: async () => { try { return await outpaintingApi.list(id) } catch (error) { expire(error); throw error } }, retry: false, refetchInterval: 5000 })
  const latest = list.data?.[0], task = useRun(userId, latest?.id ?? null), run = task.display ?? latest
  const ratio = draft ?? latest?.request.ratio ?? '16:9'
  const size = expansionSize(width, height, ratio)
  const active = run?.status === 'queued' || run?.status === 'running'
  const recoverable = run?.status === 'failed' && run.result.recoverable && Boolean(run.result.remote_task_id)
  const uncertain = run?.status === 'queued' && Boolean(run.error)
  const mutation = useMutation({
    mutationFn: async (resume: boolean) => {
      if (latest) await client.cancelQueries({ queryKey: runKey(userId, latest.id) })
      await client.cancelQueries({ queryKey: key })
      return resume && latest ? outpaintingApi.resume(id, latest.id) : outpaintingApi.submit(id, revision, { ratio })
    }, retry: false,
    onSuccess: ({ run }) => {
      client.setQueryData(runKey(userId, run.id), run)
      client.setQueryData<ExpansionRun[]>(key, previous => [{ ...run, request: latest?.id === run.id ? latest.request : { ratio } }, ...(previous ?? []).filter(item => item.id !== run.id)])
    },
    onError: error => { expire(error); void list.refetch(); if (error instanceof ApiError && error.status === 409) void onRefresh() },
    onSettled: () => { lock.current = false },
  })
  const blocked = disabled || mutation.isPending || list.isPending || list.isError || options.isError || !options.data?.enabled
  function submit(resume: boolean) {
    if (lock.current || blocked || (resume ? !(recoverable || uncertain) : active || recoverable || draftOpen || Boolean(size.error))) return
    lock.current = true; mutation.mutate(resume)
  }
  useEffect(() => { if (task.terminal) void client.invalidateQueries({ queryKey: ['edit-session', userId, id] }) }, [task.terminal, latest?.id, client, userId, id])
  return <details className="background-panel outpainting-panel" open={Boolean(run)}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><rect x="7" y="7" width="10" height="10" rx="2"/></svg>AI 扩图</span><span className="background-badge">百炼补全边缘</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body">
      <p className="background-intro">保留当前画面，居中扩展到新比例。生成一张候选，检查后再采用。</p>
      {options.data && !options.data.enabled && <p className="background-note" role="status">AI 扩图尚未启用，请完成百炼扩图配置。</p>}
      <form onSubmit={event => { event.preventDefault(); submit(false) }}>
        <div className="background-form-footer"><label htmlFor="outpainting-ratio">目标比例 <select id="outpainting-ratio" value={ratio} disabled={blocked || active || Boolean(recoverable)} onChange={event => setDraft(event.target.value as CropRatio)}>{cropRatios.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <output className="expansion-size" aria-live="polite">{size.error ?? `${width} × ${height} → ${size.width} × ${size.height} px`}</output>
          <button type="submit" className="primary background-submit expansion-submit" disabled={blocked || active || Boolean(recoverable) || draftOpen || Boolean(size.error)}>{mutation.isPending ? '正在提交…' : active ? '正在扩图…' : '生成扩图候选'}</button>
        </div>
      </form>
      <p className="background-note">调用百炼扩图，按张计费。原图不裁切、不缩放；当前仅支持不透明画布，透明画布请先换背景。</p>
      {draftOpen && <p className="background-note">请先应用或取消当前预览，再提交扩图。</p>}
      {run && <div className={`background-status status-${run.status}`} role="status"><div><span>{run.status === 'succeeded' ? '扩图候选已保存，请在会话候选中查看' : run.status === 'failed' ? '扩图未完成' : run.stage}</span><span>{run.progress}%</span></div><progress aria-label="AI扩图进度" value={run.progress} max={100}/>
        <p>基于修订 {run.result.source_revision} 的画布{run.result.source_revision !== revision ? '；当前画布已有更新，结果保留为独立候选。' : '。'}</p>
        {run.error && <p className="error-message" role="alert">{run.error}</p>}
        {(recoverable || uncertain) && <button className="secondary expansion-resume" type="button" disabled={blocked} onClick={() => submit(true)}>{recoverable ? '继续查询原云端任务' : '重新投递同一任务'}</button>}
      </div>}
      {(options.isError || list.isError || task.snapshot.isError || mutation.isError) && <p className="error-message" role="alert">{errorMessage(mutation.error ?? options.error ?? list.error ?? task.snapshot.error)}；请先刷新任务核对。</p>}
      <div className="background-refresh"><span>{task.reconnecting ? '实时连接暂断，正在查询进度。' : '采用前画布不变，采用后可撤销。'}</span><button className="text-button" type="button" disabled={list.isFetching || mutation.isPending} onClick={() => { void options.refetch(); void list.refetch(); if (latest) void task.snapshot.refetch() }}>刷新扩图任务</button></div>
    </div>
  </details>
}
