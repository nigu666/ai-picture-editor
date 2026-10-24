import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import { isTerminal, runKey, runsApi, type RunProgress, type RunStatus } from '@/api/runs'
import { ME_KEY } from '@/hooks/useAuth'
import type { User } from '@/api/auth'

export function useRun(userId: string, runId: string | null) {
  const client = useQueryClient()
  const [live, setLive] = useState<RunProgress | null>(null)
  const [connection, setConnection] = useState<{ id: string; state: 'open' | 'retrying' } | null>(null)
  const snapshot = useQuery({
    queryKey: runKey(userId, runId ?? ''),
    enabled: Boolean(runId),
    queryFn: async () => {
      try { return await runsApi.get(runId!) }
      catch (error) {
        if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
        throw error
      }
    },
    retry: false,
    refetchInterval: (query) => {
      if (isTerminal(query.state.data?.status)) return false
      if (query.state.error instanceof ApiError && [401, 404, 422].includes(query.state.error.status)) return false
      return 3000
    },
    refetchOnWindowFocus: true,
  })
  const sameRun = live?.id === runId ? live : null
  const attempt = Math.max(sameRun?.result.query_attempt ?? 0, snapshot.data?.result.query_attempt ?? 0)
  const current = (sameRun?.result.query_attempt ?? 0) === attempt ? sameRun : null
  const stored = (snapshot.data?.result.query_attempt ?? 0) === attempt ? snapshot.data : undefined
  // 快照与SSE可能交错到达；终态优先，否则采用进度不更旧的状态。
  const display = isTerminal(stored?.status) ? stored
    : current && (isTerminal(current.status) || current.progress >= (stored?.progress ?? 0)) ? current : stored
  const terminal = isTerminal(display?.status)
  const inaccessible = snapshot.error instanceof ApiError && [401, 404, 422].includes(snapshot.error.status)

  useEffect(() => {
    if (!runId || terminal || inaccessible) return
    let active = true
    const source = new EventSource(`/events/runs/${encodeURIComponent(runId)}`)
    source.onopen = () => { if (active) setConnection({ id: runId, state: 'open' }) }
    source.onerror = () => {
      if (active) {
        setConnection({ id: runId, state: 'retrying' })
        void client.invalidateQueries({ queryKey: runKey(userId, runId) })
      }
    }
    source.onmessage = (event) => {
      if (!active) return
      try {
        const payload = JSON.parse(event.data) as RunProgress
        const statuses: RunStatus[] = ['queued', 'running', 'succeeded', 'failed']
        if (payload.id !== runId || !statuses.includes(payload.status) || !Number.isFinite(payload.progress)) return
        setLive(payload)
        if (isTerminal(payload.status)) {
          source.close()
          void client.invalidateQueries({ queryKey: runKey(userId, runId) })
        }
      } catch { setConnection({ id: runId, state: 'retrying' }) }
    }
    source.addEventListener('session_expired', () => {
      source.close()
      if (active && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
    })
    source.addEventListener('unavailable', () => {
      source.close()
      if (active) {
        setConnection({ id: runId, state: 'retrying' })
        void client.invalidateQueries({ queryKey: runKey(userId, runId) })
      }
    })
    return () => { active = false; source.close() }
  }, [client, userId, runId, terminal, inaccessible])

  useEffect(() => {
    if (terminal) void client.invalidateQueries({ queryKey: ['assets', userId] })
  }, [client, userId, terminal, runId])

  return {
    snapshot,
    display,
    terminal,
    inaccessible,
    candidates: snapshot.data?.candidates ?? [],
    reconnecting: !terminal && connection?.id === runId && connection.state === 'retrying',
  }
}
