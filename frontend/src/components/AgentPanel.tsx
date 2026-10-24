import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { agentApi, type AgentStep, type AgentTurn } from '@/api/agent'
import { ApiError } from '@/api/client'
import type { User } from '@/api/auth'
import type { EditSession } from '@/api/sessions'
import { ME_KEY, errorMessage } from '@/hooks/useAuth'
import { operationLabels, type TransformOperation } from '@/api/canvas'
import { allColorControls, colorValue, neutralColors } from '@/api/colors'
import { modelsApi } from '@/api/models'

const labels: Record<AgentTurn['status'], string> = {
  planning: '正在规划', pending: '待你确认', running: '执行中', succeeded: '已完成',
  failed: '未完成', stale: '计划已过期', cancelled: '后续已停止', clarification: '需要补充说明',
}
const stepLabels = { pending: '等待执行', running: '处理中', succeeded: '已完成', failed: '未完成', cancelled: '未执行 · 已停止' }
type Action = { type: 'send'; goal: string; revision: number; request_id: string }
  | { type: 'advance' | 'confirm' | 'cancel'; id: string }
  | { type: 'retry'; id: string; revision: number; request_id: string }

const recoveryLabels = { retry_step: '从失败步骤重试', query_original: '继续查询原图片任务', read_result: '重新核对已保存结果' }

function parameters(step: AgentStep, session: EditSession) {
  if (step.tool === 'edit_image') return `「${step.params.prompt}」 · 合成已保存图层，生成1张付费整图候选，不自动采用；输出尺寸按16像素对齐`
  if (step.tool === 'edit_layer') {
    const layer = session.document.layers.find(item => item.id === step.params.layer_id), changes: string[] = []
    if (typeof step.params.visible === 'boolean') changes.push(step.params.visible ? '显示' : '隐藏')
    if (typeof step.params.locked === 'boolean') changes.push(step.params.locked ? '锁定位置' : '解锁位置')
    for (const [name, label, factor, unit] of [['center_x', '中心 X', 1, 'px'], ['center_y', '中心 Y', 1, 'px'], ['scale', '等比缩放', 100, '%'], ['rotation', '旋转', 1, '°'], ['opacity', '不透明度', 100, '%']] as const) {
      if (typeof step.params[name] === 'number') changes.push(`${label} ${+(Number(step.params[name]) * factor).toFixed(4)}${unit}`)
    }
    if (typeof step.params.position === 'number') changes.push(`从底部第 ${step.params.position + 1} 层`)
    if (typeof step.params.text === 'string') changes.push(`文字改为「${step.params.text}」`)
    for (const [key, label] of [['font_size', '字号'], ['width', '文字框宽'], ['height', '文字框高']] as const) {
      if (typeof step.params[key] === 'number') changes.push(`${label} ${step.params[key]}px`)
    }
    if (typeof step.params.fill === 'string') changes.push(`文字颜色 ${step.params.fill}`)
    if (typeof step.params.align === 'string') changes.push(`文字对齐 ${({ left: '左', center: '居中', right: '右' } as Record<string, string>)[step.params.align] ?? step.params.align}`)
    return `${layer?.name ?? '原计划图层'} · ${changes.join(' · ')} · 确认后修改，可撤销`
  }
  if (step.tool === 'erase_region' || step.tool === 'replace_region') return `${step.tool === 'erase_region' ? '消除并补全背景' : '局部替换'}：${step.params.prompt || '由模型补全周围背景（建议填写明确描述）'} · 百炼按张计费，生成一张候选后手动采用`
    if (step.tool === 'upscale_image') return `AI超分 ${step.params.scale} 倍 · 百炼按张计费，可能重建细节，候选需手动采用`
  if (step.tool === 'expand_canvas') return `扩展到 ${step.params.ratio} · 百炼补全边缘，按张计费；保留原区域，候选需手动采用`
  if (step.tool === 'replace_background') return `「${step.params.prompt}」 · ${step.params.count} 张 · 云端生成背景后本地合成，按量计费，候选需手动采用`
  if (step.tool === 'remove_background') return '本地模型分离主体，保存透明 PNG 候选；不会自动采用'
  if (step.tool === 'adjust_colors') return allColorControls.filter(({ name }) => Number(step.params[name] ?? neutralColors[name]) !== neutralColors[name]).map(control => `${control.label} ${colorValue(control, Number(step.params[control.name]))}`).join(' · ') || '恢复原始色彩'
  if (step.tool === 'transform_canvas') return operationLabels[step.params.operation as TransformOperation] ?? '画布变换'
  if (step.tool === 'layout_canvas') return [['center_x', '中心 X', 'px'], ['center_y', '中心 Y', 'px'], ['scale', '图片缩放', '%']].filter(([name]) => step.params[name] != null).map(([name, label, unit]) => `${label} ${Number(step.params[name]) * (name === 'scale' ? 100 : 1)}${unit}`).join(' · ') || '保持当前位置与大小'
  if (step.tool === 'crop_canvas') return `按 ${step.params.ratio} 居中裁剪，原图保留`
  if (step.tool === 'generate_image') return `「${step.params.prompt}」 · ${step.params.ratio} · ${step.params.count} 张`
  if (step.tool === 'adopt_candidate') {
    const index = session.assets.findIndex(asset => asset.id === step.params.asset_id)
    return index >= 0 ? `采用候选 ${index + 1}` : '目标图片已不在当前候选墙，请重新规划'
  }
  return step.tool === 'undo_canvas' ? '撤销一次画布编辑' : '重做一次画布编辑'
}

export default function AgentPanel({ userId, session, editingBusy }: { userId: string; session: EditSession; editingBusy: boolean }) {
  const client = useQueryClient()
  const [goal, setGoal] = useState('')
  const lock = useRef(false)
  const records = useRef<HTMLDivElement>(null)
  const restored = useRef(false)
  const progressCursor = useRef('')
  const retryRequests = useRef<Record<string, { revision: number; attempt: number; request_id: string }>>({})
  const request = useRef<{ goal: string; revision: number; request_id: string } | null>(null)
  const key = ['agent-messages', userId, session.id]
  function handleError(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
    if (error instanceof ApiError && error.status === 409) void client.invalidateQueries({ queryKey: ['edit-session', userId, session.id] })
  }
  const models = useQuery({ queryKey: ['model-options', userId], queryFn: async () => {
    try { return await modelsApi.options() } catch (error) { handleError(error); throw error }
  }, retry: false })
  const turns = useQuery({ queryKey: key, queryFn: async () => {
    try { return await agentApi.list(session.id) } catch (error) { handleError(error); throw error }
  }, retry: false })
  const action = useMutation({
    mutationFn: (value: Action) => value.type === 'send' ? agentApi.send(session.id, { goal: value.goal, revision: value.revision, request_id: value.request_id })
      : value.type === 'cancel' ? agentApi.cancel(session.id, value.id)
      : value.type === 'retry' ? agentApi.retry(session.id, value.id, { revision: value.revision, request_id: value.request_id })
      : agentApi.advance(session.id, value.id, value.type === 'confirm'),
    retry: false,
    onSuccess: (row, value) => {
      if (client.getQueryData<User>(ME_KEY)?.id !== userId) return
      client.setQueryData<AgentTurn[]>(key, previous => [...(previous ?? []).filter(t => t.id !== row.id), row].sort((a, b) => a.created_at.localeCompare(b.created_at)))
      void client.invalidateQueries({ queryKey: key })
      if (value.type === 'send') {
        setGoal(previous => previous.trim() === value.goal ? '' : previous); request.current = null
        window.requestAnimationFrame(() => records.current?.scrollTo({ top: records.current.scrollHeight }))
      }
      if (value.type !== 'send') {
        void client.invalidateQueries({ queryKey: ['edit-session', userId, session.id] })
        void client.invalidateQueries({ queryKey: ['sessions', userId] })
        void client.invalidateQueries({ queryKey: ['assets', userId] })
      }
    },
    onError: handleError,
    onSettled: () => { lock.current = false },
  })
  const mutate = action.mutate
  useEffect(() => {
    if (!restored.current && turns.data?.length && records.current) {
      records.current.scrollTop = records.current.scrollHeight
      restored.current = true
    }
  }, [turns.data])
  // 自动读取只推进已确认计划；网络失败后停止轮询，保留显式恢复入口。
  useEffect(() => {
    const activeTurns = turns.data?.filter(turn => turn.status === 'running' || turn.status === 'planning' || ['cancelled', 'stale'].includes(turn.status) && turn.steps.some(step => step.status === 'running')) ?? []
    if (!activeTurns.length || action.isPending || action.isError || turns.isError) return
    const timer = window.setTimeout(() => {
      const cursor = activeTurns.findIndex(turn => turn.id === progressCursor.current)
      const active = activeTurns[(cursor + 1) % activeTurns.length]
      if (!lock.current) { lock.current = true; progressCursor.current = active.id; mutate({ type: 'advance', id: active.id }) }
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [turns.data, action.isPending, action.isError, turns.isError, mutate])
  function run(value: Action) {
    if (lock.current) return
    lock.current = true
    mutate(value)
  }
  function send() {
    const text = goal.trim()
    if (!text || !models.data?.planner_configured || busy) return
    if (!request.current || request.current.goal !== text || request.current.revision !== session.revision) {
      request.current = { goal: text, revision: session.revision, request_id: crypto.randomUUID() }
    }
    run({ type: 'send', ...request.current })
  }
  function retryTurn(turn: AgentTurn) {
    const attempt = turn.steps.find(step => step.status === 'failed')?.retry_count ?? 0
    const previous = retryRequests.current[turn.id]
    if (!previous || previous.revision !== session.revision || previous.attempt !== attempt) {
      retryRequests.current[turn.id] = { revision: session.revision, attempt, request_id: crypto.randomUUID() }
    }
    const request = retryRequests.current[turn.id]
    run({ type: 'retry', id: turn.id, revision: request.revision, request_id: request.request_id })
  }
  const busy = action.isPending || editingBusy
  return <section className="agent-section" aria-labelledby="agent-heading">
    <div className="section-heading"><div><p className="eyebrow">确认后执行</p><h2 id="agent-heading">AI 修图助手</h2></div><span className="agent-mode">{models.data ? models.data.planner_configured ? '模型已配置' : '模型待配置' : '正在读取配置'}</span></div>
    <div className="agent-layout">
      <form className="agent-compose" onSubmit={event => { event.preventDefault(); send() }}>
        <label htmlFor="agent-goal">当前会话的修图要求</label>
        <textarea id="agent-goal" value={goal} onChange={event => setGoal(event.target.value)} maxLength={1500} rows={3}
          placeholder="把杯子改成酒红色，保持背景和光线。" disabled={action.isPending && action.variables?.type === 'send'} />
        <div className="agent-compose-footer"><span>{goal.length} / 1500</span><button className="primary" type="submit" disabled={busy || !models.data?.planner_configured || !goal.trim() || turns.isError || turns.isPending}>
          {action.isPending && action.variables?.type === 'send' ? '正在规划…' : '生成修改计划'}
        </button></div>
        <p className="agent-safety-note">基于已保存画布规划，确认后执行。{models.data?.reference_configured && 'AI整图编辑按张计费，候选需手动采用。'}</p>
        <details className="agent-config-notes"><summary>模型与适用范围</summary>
          <span className="agent-mode">{models.data ? `${models.data.planner_provider === 'dashscope' ? '百炼' : '智谱'}${models.data.planner_configured ? '已配置' : '待配置'} · 文生图：${!models.data.image_configured ? '待配置' : models.data.image_provider === 'mock' ? 'Mock' : models.data.image_model}` : '正在读取模型配置'}</span>
          <p className="agent-help">{models.data ? `${models.data.vision_enabled ? '规划与看图' : '规划'}使用 ${models.data.planner_model}。` : ''}发送时分析已保存的画布，临时预览与其他候选不传图。</p>
          {models.data?.reference_configured && <p className="agent-help">AI整图编辑会合成已保存图层，生成1张付费候选，不自动替换画布。画布需不透明，宽高均为512～2048像素，输出按16像素对齐。</p>}
          <p className="agent-help">当前会话 · 画布版本 {session.revision}。更换会话会读取各自的对话记录。</p>
        </details>
        {models.data && !models.data.planner_configured && <p className="agent-help" role="status">模型密钥尚未填写。配置 .env 并重启后端后，即可发送要求；本地画布工具可继续使用。</p>}
        {models.isError && <p className="error-message" role="alert">模型配置读取失败，请重新读取。</p>}
      </form>
      <div className="agent-conversation" aria-label="会话计划记录" aria-busy={action.isPending}>
        <div className="agent-record-heading"><div><h3>计划记录</h3>{(turns.data?.length ?? 0) > 1 && <span className="agent-scroll-hint">{turns.data!.length} 条记录 · 上下滚动查看</span>}</div><button className="text-button" type="button" disabled={action.isPending || turns.isFetching} onClick={() => { action.reset(); void models.refetch(); void turns.refetch() }}>重新读取</button></div>
        {turns.isPending && <p className="agent-empty" role="status">正在读取本会话的计划…</p>}
        {turns.isError && <div className="error-message" role="alert">{errorMessage(turns.error)}<p>点击“重新读取”恢复记录。</p></div>}
        {action.isError && <div className="error-message" role="alert">{errorMessage(action.error)}<p>提交结果尚未确认。请重新读取记录后核对；原指令仍保留。</p></div>}
        {turns.data?.length === 0 && <div className="agent-empty"><span className="agent-empty-icon" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none"><path d="M7 6h18v15H14l-7 5V6Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"/><path d="M12 11h8m-8 5h5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg></span><h3>从一句明确的要求开始</h3><p>计划会列出步骤和参数。确认前，画布保持当前状态。</p></div>}
        <div className="agent-records" ref={records} tabIndex={turns.data?.length ? 0 : undefined} aria-label="计划记录，可上下滚动">{turns.data?.map(turn => <article className={`agent-turn is-${turn.status}`} key={turn.id} data-turn={turn.id}>
          <div className="agent-turn-heading"><span className={`agent-state state-${turn.status}`}>{turn.status === 'clarification' && turn.analysis ? '分析已返回' : labels[turn.status]}</span><time dateTime={turn.created_at}>{new Date(turn.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time></div>
          <p className="agent-goal-text">{turn.goal}</p>
          <p className="agent-reply" role="status">{turn.message}</p>
          {turn.progress && turn.progress.total > 0 && <p className="agent-help">已完成 {turn.progress.completed} / {turn.progress.total} 步 · 按顺序执行，每次推进一步。{turn.status === 'pending' ? '尚待你确认。' : ''}</p>}
          {turn.analysis && <div className="agent-help"><strong>模型观察与建议 · 尚未执行</strong><p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{turn.analysis}</p></div>}
          {turn.planner_source === 'zhipu' && <p className="agent-help">智谱规划与视觉分析</p>}
          {turn.planner_source === 'dashscope' && <p className="agent-help">百炼千问规划与视觉分析</p>}
          {turn.planner_source === 'scripted_test_only' && <p className="agent-help">验收脚本规划器 · 未调用真实模型</p>}
          {turn.steps.length > 0 && <ol className="agent-steps">{turn.steps.map((step, index) => <li key={step.id}>
            <span className="agent-step-number">{index + 1}</span><div><div className="agent-step-heading"><strong>{step.label}</strong><span>{step.execution?.label ?? (step.status === 'pending' && ['stale', 'failed', 'cancelled'].includes(turn.status) ? turn.status === 'cancelled' ? '已取消' : '已停止' : stepLabels[step.status])}</span></div><p>{parameters(step, session)}</p>
              {step.execution && <><p className="agent-help">{step.execution.reason}</p><p className="agent-help">{step.execution.dependencies.length ? `依赖：${step.execution.dependencies.map(item => `${item.number ? `第 ${item.number} 步` : item.id}「${item.label}」· ${item.status === 'missing' ? '不存在' : stepLabels[item.status]}`).join('；')}` : '没有前置依赖。'}</p></>}
              {step.selection && <p className="agent-help">已固定画布 {step.selection.revision} 的选区 v{step.selection.version} · {step.selection.selected_pixels.toLocaleString('zh-CN')} 像素。确认后使用此选区；之后修改或清除选区不会改变本计划。要改范围，请取消后重新发送。</p>}
              {step.status === 'failed' && step.recovery && <p className="agent-help">{step.recovery.note}</p>}
              <details><summary>查看完整参数与依赖</summary><pre>{JSON.stringify({ params: step.params, depends_on: step.depends_on, ...(step.run_id ? { task_id: step.run_id } : {}) }, null, 2)}</pre></details>
              {step.run_id && <div className="agent-task"><p>{step.provider === 'mock' ? 'Mock 占位图任务' : '图片生成任务'} · {step.stage} · {step.progress ?? 0}%</p><progress aria-label="计划生成任务进度" max={100} value={step.progress ?? 0} /></div>}
            </div>
          </li>)}</ol>}
          <div className="agent-turn-actions"><span>基于画布版本 {turn.revision}</span>
            {turn.status === 'pending' && <><button className="secondary" disabled={busy} onClick={() => run({ type: 'cancel', id: turn.id })}>取消计划</button><button className="primary" disabled={busy || session.revision !== turn.expected_revision} onClick={() => run({ type: 'confirm', id: turn.id })}>确认执行</button>{session.revision !== turn.expected_revision && <span className="agent-help">画布已变化，请重新规划。</span>}</>}
            {(turn.status === 'running' || turn.status === 'planning') && <button className="secondary" disabled={busy} onClick={() => run({ type: 'advance', id: turn.id })}>读取进度并继续</button>}
            {turn.status === 'running' && <button className="secondary" disabled={busy} onClick={() => run({ type: 'cancel', id: turn.id })}>停止后续步骤</button>}
            {['cancelled', 'stale'].includes(turn.status) && turn.steps.some(step => step.status === 'running') && <button className="secondary" disabled={busy} onClick={() => run({ type: 'advance', id: turn.id })}>仅核对已提交任务</button>}
            {turn.status === 'failed' && turn.steps.find(step => step.status === 'failed')?.recovery && <button className="secondary" disabled={busy || session.revision !== turn.expected_revision} onClick={() => retryTurn(turn)}>{recoveryLabels[turn.steps.find(step => step.status === 'failed')!.recovery!.mode]}</button>}
            {turn.status === 'failed' && turn.steps.some(step => step.recovery) && session.revision !== turn.expected_revision && <span className="agent-help">画布已变化，请重新规划。</span>}
            {['failed', 'stale', 'clarification'].includes(turn.status) && <button className="text-button" disabled={busy} onClick={() => { setGoal(turn.goal); document.getElementById('agent-goal')?.focus() }}>再次使用指令</button>}
          </div>
        </article>)}</div>
        <p className="agent-history-note">显示最近 50 条及进行中的记录。关闭页面后已排队任务继续，后续步骤在重新打开时推进。</p>
      </div>
    </div>
  </section>
}
