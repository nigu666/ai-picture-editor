import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import type { User } from '@/api/auth'
import { generationHistoryKey, runsApi, type GenerationRecord } from '@/api/runs'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'

const statuses = { queued: '等待执行', running: '正在生成', succeeded: '生成完成', failed: '生成失败' }

export default function GenerationHistory({ userId, currentId, openingDisabled, reuseDisabled, onOpen, onReuse }: {
  userId: string; currentId: string | null; openingDisabled: boolean; reuseDisabled: boolean
  onOpen: (id: string) => void; onReuse: (record: GenerationRecord) => void
}) {
  const client = useQueryClient()
  const [cursors, setCursors] = useState<(string | null)[]>([null])
  const before = cursors[cursors.length - 1]
  const records = useQuery({
    queryKey: [...generationHistoryKey(userId), before],
    queryFn: async () => {
      try { return await runsApi.history(before) } catch (error) {
        if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
        throw error
      }
    },
    retry: false,
  })

  function latest() {
    setCursors([null])
    void client.invalidateQueries({ queryKey: generationHistoryKey(userId) })
  }

  return <section className="generation-history" aria-labelledby="generation-history-heading">
    <div className="agent-record-heading"><div><h3 id="generation-history-heading">生成记录</h3>
      <p className="generation-help">仅显示当前账号的普通生图，每页10条；查看记录不会重新生成。</p></div>
      <button className="text-button" type="button" disabled={records.isFetching || openingDisabled} onClick={latest}>最新记录</button></div>
    {records.isPending && <p role="status">正在读取记录…</p>}
    {records.isError && <p className="error-message" role="alert">{errorMessage(records.error)}<button className="text-button" type="button" onClick={() => { void records.refetch() }} disabled={records.isFetching}>重新读取</button></p>}
    {records.data?.items.length === 0 && <p className="generation-help">还没有生成记录。提交后的任务会保存在这里。</p>}
    <ol className="generation-records" aria-label="已保存的生成任务">
      {records.data?.items.map((record) => <li key={record.id} className={`generation-record ${currentId === record.id ? 'is-current' : ''}`}>
        <div className="generation-record-heading"><time dateTime={record.created_at}>{new Date(record.created_at).toLocaleString('zh-CN', { hour12: false })}</time>
          <span>{statuses[record.status]}{record.status === 'running' ? ` · ${record.progress}%` : ''}{currentId === record.id ? ' · 当前查看' : ''}</span></div>
        <p className="generation-record-prompt">{record.prompt}</p>
        <p className="generation-help">{record.provider === 'mock' ? 'Mock 占位图' : record.model ?? record.provider} · {record.width} × {record.height} · 请求{record.count}张{record.reference_asset_ids?.length ? ` · 参考${record.reference_asset_ids.length}张` : ''}</p>
        <div className="generation-record-actions">
          <button className="secondary" type="button" disabled={openingDisabled} aria-pressed={currentId === record.id} onClick={() => onOpen(record.id)}>查看任务与候选</button>
          <button className="text-button" type="button" disabled={reuseDisabled} onClick={() => onReuse(record)}>复用参数到表单</button>
        </div>
      </li>)}
    </ol>
    {(cursors.length > 1 || records.data?.next_cursor) && <nav className="generation-history-pagination" aria-label="生成记录翻页">
      <button className="secondary" type="button" disabled={cursors.length === 1 || records.isFetching} onClick={() => setCursors((previous) => previous.slice(0, -1))}>较新记录</button>
      <span>第{cursors.length}页</span>
      <button className="secondary" type="button" disabled={!records.data?.next_cursor || records.isFetching} onClick={() => {
        const next = records.data?.next_cursor
        if (next) setCursors((previous) => [...previous, next])
      }}>更早记录</button>
    </nav>}
  </section>
}
