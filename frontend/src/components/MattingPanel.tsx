import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { mattingApi } from '@/api/matting'
import { runKey } from '@/api/runs'
import { useRun } from '@/hooks/useRun'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import { ApiError } from '@/api/client'
import type { User } from '@/api/auth'

export default function MattingPanel({ id, revision, userId, disabled, draftOpen, onRefresh }: {
  id: string; revision: number; userId: string; disabled: boolean; draftOpen: boolean; onRefresh: () => unknown
}) {
  const client = useQueryClient()
  const key = ['matting-runs', userId, id]
  const lock = useRef(false)
  function expire(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
  }
  const list = useQuery({ queryKey: key, queryFn: async () => {
    try { return await mattingApi.list(id) } catch (error) { expire(error); throw error }
  }, retry: false, refetchInterval: 5000 })
  const latest = list.data?.[0]
  const task = useRun(userId, latest?.id ?? null)
  const run = task.display ?? latest
  const active = run?.status === 'queued' || run?.status === 'running'
  const uncertain = run?.status === 'queued' && Boolean(run.error)
  const mutation = useMutation({ mutationFn: () => mattingApi.submit(id, revision), retry: false,
    onSuccess: ({ run }) => { client.setQueryData(runKey(userId, run.id), run); client.setQueryData(key, [run, ...(list.data ?? []).filter(item => item.id !== run.id)]) },
    onError: error => { expire(error); void list.refetch(); if (error instanceof ApiError && error.status === 409) void onRefresh() },
    onSettled: () => { lock.current = false },
  })
  useEffect(() => {
    if (task.terminal) void client.invalidateQueries({ queryKey: ['edit-session', userId, id] })
  }, [task.terminal, latest?.id, client, userId, id])
  return <section className="matting-panel" aria-label="去背景工具">
    <div className="matting-heading"><div><h3><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4M7 18c0-4 10-4 10 0"/><circle cx="12" cy="9" r="3"/></svg>去背景<span>本地处理</span></h3><p>保留主体，生成透明 PNG 候选；检查后再采用。</p></div>
      <button type="button" className="secondary matting-submit" disabled={disabled || draftOpen || (active && !uncertain) || mutation.isPending || list.isPending || list.isError}
        onClick={() => { if (!lock.current) { lock.current = true; mutation.mutate() } }}>{mutation.isPending ? '正在提交…' : uncertain ? '重新投递同一任务' : active ? '正在去背景…' : '生成透明候选'}</button></div>
    {draftOpen && <p className="matting-note">请先应用或取消当前预览，再去背景。</p>}
    {run && <div className={`matting-status status-${run.status}`} role="status">
      <div><span>{run.status === 'succeeded' ? '透明候选已保存，请在会话候选中查看' : run.status === 'failed' ? '去背景未完成' : run.stage}</span><span>{run.progress}%</span></div>
      <progress aria-label="去背景进度" value={run.progress} max={100} />
      {run.result.source_revision && <p>基于修订 {run.result.source_revision} 的画布{run.result.source_revision !== revision ? '；当前画布已有更新，结果保留为独立候选。' : '。'}</p>}
      {run.error && <p className="error-message" role="alert">{run.error}</p>}
    </div>}
    {(list.isError || task.snapshot.isError || mutation.isError) && <div className="error-message" role="alert"><p>{errorMessage(mutation.error ?? list.error ?? task.snapshot.error)}；提交结果未确认时，请先刷新任务核对。</p></div>}
    <div className="matting-footer"><p>{task.reconnecting ? '实时连接暂断，正在自动查询进度。' : '不会覆盖原图；采用后支持撤销。'}</p><button type="button" className="text-button" disabled={list.isFetching || mutation.isPending} onClick={() => { void list.refetch(); if (latest) void task.snapshot.refetch() }}>刷新去背景任务</button></div>
  </section>
}
