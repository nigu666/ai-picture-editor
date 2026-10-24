import { useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import type { Asset } from '@/api/assets'
import type { User } from '@/api/auth'
import { ApiError } from '@/api/client'
import { sessionsApi, type EditSession } from '@/api/sessions'
import { ME_KEY } from './useAuth'
import { canvasTool } from '@/api/canvas'

type Change = { action: 'adopt' | 'assets' | 'undo' | 'redo' | 'rename' | 'layers'; body?: object }
type Operation = Change | { action: 'create'; asset: Asset; ids: string[] }
  | { action: 'tool'; tool: 'transform_canvas' | 'crop_canvas' | 'adjust_colors' | 'layout_canvas' | 'edit_layer'; params: object }

export function useEditorSession(userId: string) {
  const client = useQueryClient()
  const [search, setSearch] = useSearchParams()
  const id = search.get('session')
  const lock = useRef(false)
  const listKey = ['sessions', userId]
  const detailKey = ['edit-session', userId, id]
  function expire(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) {
      client.setQueryData(ME_KEY, null)
    }
  }
  const list = useQuery({ queryKey: listKey, queryFn: async () => {
    try { return await sessionsApi.list() } catch (error) { expire(error); throw error }
  }, retry: false })
  const detail = useQuery({ queryKey: detailKey, enabled: Boolean(id), queryFn: async () => {
    try { return await sessionsApi.get(id!) } catch (error) { expire(error); throw error }
  }, retry: false, refetchInterval: false })
  const mutation = useMutation({
    mutationFn: (operation: Operation) => {
      if (operation.action === 'create') return sessionsApi.create(operation.asset, operation.ids)
      if (!id || !detail.data || detail.isError) throw new Error('请先重新读取当前会话')
      if (operation.action === 'tool') return canvasTool(id, detail.data.revision, operation.tool, operation.params)
      return sessionsApi.change(id, operation.action, { revision: detail.data.revision, ...operation.body })
    },
    retry: false,
    onSuccess: (row: EditSession) => {
      client.setQueryData(['edit-session', userId, row.id], row)
      void client.invalidateQueries({ queryKey: listKey })
      if (client.getQueryData<User>(ME_KEY)?.id === userId) {
        setSearch((previous) => { previous.set('session', row.id); return previous })
      }
    },
    onError: (error) => {
      expire(error)
      if (error instanceof ApiError && error.status === 409) void detail.refetch()
      // 无法确认提交结果时刷新列表，让用户核对；不自动重试写入。
      void client.invalidateQueries({ queryKey: listKey })
    },
    onSettled: () => { lock.current = false },
  })
  function execute(operation: Operation, onSuccess?: () => void) {
    if (lock.current) return
    lock.current = true
    mutation.mutate(operation, { onSuccess })
  }
  return {
    id, list, detail, mutation,
    change: (operation: Change, onSuccess?: () => void) => execute(operation, onSuccess),
    tool: (tool: 'transform_canvas' | 'crop_canvas' | 'adjust_colors' | 'layout_canvas' | 'edit_layer', params: object, onSuccess?: () => void) => execute({ action: 'tool', tool, params }, onSuccess),
    create: (asset: Asset, ids: string[] = []) => execute({ action: 'create', asset, ids }),
    select: (next: string | null) => {
      if (lock.current) return
      mutation.reset()
      setSearch((previous) => { if (next) previous.set('session', next); else previous.delete('session'); return previous })
    },
  }
}

export type EditorController = ReturnType<typeof useEditorSession>
