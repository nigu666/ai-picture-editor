import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { backgroundApi, type BackgroundInput, type BackgroundRun } from '@/api/background'
import { runKey } from '@/api/runs'
import { useRun } from '@/hooks/useRun'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import { ApiError } from '@/api/client'
import type { User } from '@/api/auth'

export default function BackgroundPanel({ id, revision, userId, disabled, draftOpen, onRefresh }: {
  id: string; revision: number; userId: string; disabled: boolean; draftOpen: boolean; onRefresh: () => unknown
}) {
  const client = useQueryClient(), lock = useRef(false)
  const [draft, setDraft] = useState<BackgroundInput | null>(null)
  const key = ['background-runs', userId, id]
  function expire(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
  }
  const options = useQuery({ queryKey: ['background-options', userId], queryFn: async () => { try { return await backgroundApi.options() } catch (error) { expire(error); throw error } }, retry: false })
  const list = useQuery({ queryKey: key, queryFn: async () => { try { return await backgroundApi.list(id) } catch (error) { expire(error); throw error } }, retry: false, refetchInterval: 5000 })
  const latest = list.data?.[0], task = useRun(userId, latest?.id ?? null), run = task.display ?? latest
  const providerLabel = options.data?.label ?? '云端模型'
  const values = draft ?? latest?.request ?? { prompt: '', count: 1 }
  const active = run?.status === 'queued' || run?.status === 'running'
  const uncertain = run?.status === 'queued' && Boolean(run.error)
  const staleRetry = uncertain && run.result.source_revision !== revision
  const mutation = useMutation({ mutationFn: (input: BackgroundInput) => backgroundApi.submit(id, revision, input), retry: false,
    onSuccess: ({ run }, input) => { client.setQueryData(runKey(userId, run.id), run); client.setQueryData<BackgroundRun[]>(key, previous => [{ ...run, request: input }, ...(previous ?? []).filter(item => item.id !== run.id)]) },
    onError: error => { expire(error); void list.refetch(); if (error instanceof ApiError && error.status === 409) void onRefresh() },
    onSettled: () => { lock.current = false },
  })
  useEffect(() => { if (task.terminal) void client.invalidateQueries({ queryKey: ['edit-session', userId, id] }) }, [task.terminal, latest?.id, client, userId, id])
  function submit(event: FormEvent) {
    event.preventDefault()
    if (lock.current || disabled || draftOpen || !values.prompt.trim() || values.prompt.length > 800 || !options.data?.enabled || (active && !uncertain) || staleRetry || mutation.isPending || list.isPending || list.isError || options.isError) return
    lock.current = true; mutation.mutate({ prompt: values.prompt.trim(), count: values.count })
  }
  return <details className="background-panel" open={Boolean(run)}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="m4 17 5-5 4 4 3-3 5 5"/><circle cx="16" cy="8" r="2"/></svg>换背景</span><span className="background-badge">{providerLabel} · 本地合成</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body"><p className="background-intro">描述新场景，生成背景并合成主体。检查候选后再采用。</p>
      {options.data && !options.data.enabled && <p className="background-note" role="status">{providerLabel}尚未配置密钥。填写开发项目 .env 后重启后端，再刷新此页。</p>}
      <form onSubmit={submit}><label htmlFor="background-prompt">新背景描述</label><textarea id="background-prompt" rows={3} maxLength={800} value={values.prompt} placeholder="例如：柔和自然光下的浅蓝色摄影棚，背景简洁" disabled={disabled || active || mutation.isPending || list.isPending || list.isError}
        onChange={event => setDraft({ ...values, prompt: event.target.value })} />
        <div className="background-form-footer"><label htmlFor="background-count">候选数量 <select id="background-count" value={values.count} disabled={disabled || active || mutation.isPending || list.isPending || list.isError} onChange={event => setDraft({ ...values, count: Number(event.target.value) })}>{[1, 2, 4].map(count => <option key={count} value={count}>{count} 张</option>)}</select></label><span>{values.prompt.length}/800</span>
          <button type="submit" className="primary background-submit" disabled={disabled || draftOpen || !options.data?.enabled || list.isPending || list.isError || !values.prompt.trim() || values.prompt.length > 800 || mutation.isPending || (active && !uncertain) || staleRetry}>{mutation.isPending ? '正在提交…' : uncertain ? '重新投递同一任务' : active ? '正在生成背景…' : '生成换背景候选'}</button></div>
      </form><p className="background-note">将调用{providerLabel}，按生成数量计费。主体边缘取决于抠图效果，不会自动重打光。</p>
      {draftOpen && <p className="background-note">请先应用或取消当前预览，再生成背景。</p>}
      {run && <div className={`background-status status-${run.status}`} role="status"><div><span>{run.status === 'succeeded' ? '合成候选已保存，请在会话候选中查看' : run.status === 'failed' ? (run.result.asset_ids?.length ? '换背景未完成；已保存的候选仍可查看' : '换背景未完成') : run.stage}</span><span>{run.progress}%</span></div><progress aria-label="换背景进度" value={run.progress} max={100}/>
        <p>基于修订 {run.result.source_revision} 的画布{run.result.source_revision !== revision ? '；当前画布已有更新，结果保留为独立候选。' : '。'}</p>{run.error && <p className="error-message" role="alert">{run.error}</p>}</div>}
      {(options.isError || list.isError || task.snapshot.isError || mutation.isError) && <div className="error-message" role="alert">{errorMessage(mutation.error ?? options.error ?? list.error ?? task.snapshot.error)}；提交结果未确认时，请先刷新任务核对。</div>}
      <div className="background-refresh"><span>{task.reconnecting ? '实时连接暂断，正在查询进度。' : '原图保留，候选采用后可撤销。'}</span><button type="button" className="text-button" disabled={list.isFetching || mutation.isPending} onClick={() => { void options.refetch(); void list.refetch(); if (latest) void task.snapshot.refetch() }}>刷新换背景任务</button></div>
    </div>
  </details>
}
