import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { upscalingApi, upscaleSize, type UpscaleRun } from '@/api/upscaling'
import { runKey } from '@/api/runs'
import { useRun } from '@/hooks/useRun'
import { ApiError } from '@/api/client'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import type { User } from '@/api/auth'

type UpscaleFactor = 2 | 4

export default function UpscalingPanel({ id, revision, width, height, userId, disabled, draftOpen, onRefresh }: {
  id: string; revision: number; width: number; height: number; userId: string
  disabled: boolean; draftOpen: boolean; onRefresh: () => unknown
}) {
  const client = useQueryClient(), lock = useRef(false)
  const [draft, setDraft] = useState<UpscaleFactor | null>(null)
  const key = ['upscaling-runs', userId, id]
  function expire(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
  }
  const options = useQuery({ queryKey: ['upscaling-options', userId], queryFn: async () => { try { return await upscalingApi.options() } catch (error) { expire(error); throw error } }, retry: false })
  const list = useQuery({ queryKey: key, queryFn: async () => { try { return await upscalingApi.list(id) } catch (error) { expire(error); throw error } }, retry: false, refetchInterval: 5000 })
  const latest = list.data?.[0], task = useRun(userId, latest?.id ?? null), run = task.display ?? latest
  const scale = draft ?? latest?.request.scale ?? 2
  const size = upscaleSize(width, height, scale)
  const active = run?.status === 'queued' || run?.status === 'running'
  const recoverable = run?.status === 'failed' && run.result.recoverable && Boolean(run.result.remote_task_id)
  const uncertain = run?.status === 'queued' && Boolean(run.error)
  const mutation = useMutation({
    mutationFn: async (resume: boolean) => {
      if (latest) await client.cancelQueries({ queryKey: runKey(userId, latest.id) })
      await client.cancelQueries({ queryKey: key })
      return resume && latest ? upscalingApi.resume(id, latest.id) : upscalingApi.submit(id, revision, { scale })
    }, retry: false,
    onSuccess: ({ run }) => {
      client.setQueryData(runKey(userId, run.id), run)
      client.setQueryData<UpscaleRun[]>(key, previous => [{ ...run, request: latest?.id === run.id ? latest.request : { scale } }, ...(previous ?? []).filter(item => item.id !== run.id)])
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
  return <details className="background-panel upscaling-panel" open={Boolean(run)}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 16l8-8m-5 0h5v5"/></svg>AI 超分</span><span className="background-badge">百炼增强细节</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body">
      <p className="background-intro">以 2 倍或 4 倍提高分辨率，保持构图。生成一张候选，检查后再采用。</p>
      {options.data && !options.data.enabled && <p className="background-note" role="status">AI 超分尚未启用，请完成百炼超分配置。</p>}
      <form onSubmit={event => { event.preventDefault(); submit(false) }}>
        <div className="background-form-footer"><label htmlFor="upscaling-scale">放大倍率 <select id="upscaling-scale" value={scale} disabled={blocked || active || Boolean(recoverable)} onChange={event => setDraft(Number(event.target.value) as UpscaleFactor)}>{([2, 4] as const).map(value => <option key={value} value={value}>{value} 倍</option>)}</select></label>
          <output className="upscale-size" aria-live="polite">{size.error ?? `${width} × ${height} → ${size.width} × ${size.height} px`}</output>
          <button type="submit" className="primary background-submit upscale-submit" disabled={blocked || active || Boolean(recoverable) || draftOpen || Boolean(size.error)}>{mutation.isPending ? '正在提交…' : active ? '正在超分…' : '生成超分候选'}</button>
        </div>
      </form>
      <p className="background-note">调用百炼超分，按张计费。可能重建或改变细节，请对比后采用。当前支持不透明画布，输出每边最多 4096 px。</p>
      {draftOpen && <p className="background-note">请先应用或取消当前预览，再提交超分。</p>}
      {run && <div className={`background-status status-${run.status}`} role="status"><div><span>{run.status === 'succeeded' ? '超分候选已保存，请在会话候选中查看' : run.status === 'failed' ? '超分未完成' : run.stage}</span><span>{run.progress}%</span></div><progress aria-label="AI超分进度" value={run.progress} max={100}/>
        <p>基于修订 {run.result.source_revision} 的画布{run.result.source_revision !== revision ? '；当前画布已有更新，结果保留为独立候选。' : '。'}</p>
        {run.error && <p className="error-message" role="alert">{run.error}</p>}
        {(recoverable || uncertain) && <button className="secondary upscale-resume" type="button" disabled={blocked} onClick={() => submit(true)}>{recoverable ? '继续查询原云端任务' : '重新投递同一任务'}</button>}
      </div>}
      {(options.isError || list.isError || task.snapshot.isError || mutation.isError) && <p className="error-message" role="alert">{errorMessage(mutation.error ?? options.error ?? list.error ?? task.snapshot.error)}；请先刷新任务核对。</p>}
      <div className="background-refresh"><span>{task.reconnecting ? '实时连接暂断，正在查询进度。' : '采用前画布不变，采用后可撤销。'}</span><button className="text-button" type="button" disabled={list.isFetching || mutation.isPending} onClick={() => { void options.refetch(); void list.refetch(); if (latest) void task.snapshot.refetch() }}>刷新超分任务</button></div>
    </div>
  </details>
}
