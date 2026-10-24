import { api } from './client'

export type AgentStep = {
  id: string; tool: string; label: string; params: Record<string, unknown>; depends_on: string[]
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  run_id?: string; progress?: number; stage?: string; provider?: string; asset_ids?: string[]
  selection?: { revision: number; version: number; selected_pixels: number } | null
  recovery?: { mode: 'retry_step' | 'query_original' | 'read_result'; note: string }
  retry_count?: number
  execution?: {
    state: 'succeeded' | 'failed' | 'cancelled' | 'running' | 'awaiting_confirmation' | 'blocked' | 'waiting_dependency' | 'ready' | 'waiting_order'
    label: string; reason: string
    dependencies: { id: string; number: number | null; label: string; status: AgentStep['status'] | 'missing' }[]
  }
}
export type AgentTurn = {
  id: string; session_id: string; request_id: string; goal: string; revision: number; expected_revision: number
  status: 'planning' | 'pending' | 'running' | 'succeeded' | 'failed' | 'stale' | 'cancelled' | 'clarification'
  message: string; analysis: string; planner_source: string; steps: AgentStep[]; created_at: string
  progress?: { completed: number; total: number; current_step_id: string | null; execution_order: 'serial' }
}
const base = (id: string) => `/sessions/${encodeURIComponent(id)}/agent`
export const agentApi = {
  list: (id: string) => api.get<AgentTurn[]>(`${base(id)}/messages`),
  send: (id: string, body: { goal: string; revision: number; request_id: string }) => api.post<AgentTurn>(`${base(id)}/messages`, body),
  advance: (id: string, turn: string, confirm = false) => api.post<AgentTurn>(`${base(id)}/plans/${turn}/advance`, { confirm }),
  cancel: (id: string, turn: string) => api.post<AgentTurn>(`${base(id)}/plans/${turn}/cancel`),
  retry: (id: string, turn: string, body: { revision: number; request_id: string }) => api.post<AgentTurn>(`${base(id)}/plans/${turn}/retry`, body),
}
