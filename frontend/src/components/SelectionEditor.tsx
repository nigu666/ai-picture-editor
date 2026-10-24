import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import EditorCanvas from './EditorCanvas'
import RegionPanel from './RegionPanel'
import PromotePanel from './PromotePanel'
import type { EditSession } from '@/api/sessions'
import type { CropBox } from '@/api/canvas'
import { selectionApi, selectionKey, type SelectionCommand, type SelectionStroke, type SelectionState, type SelectionPoint } from '@/api/selection'
import { ApiError } from '@/api/client'
import type { User } from '@/api/auth'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'

export default function SelectionEditor({ row, userId, disabled, draftOpen, onRefresh, cropPreview, colorPreviewUrl, layoutPreviewUrl, layoutOpen, layerInteraction }: {
  row: EditSession; userId: string; disabled: boolean; draftOpen: boolean; onRefresh: () => void
  cropPreview?: CropBox | null; colorPreviewUrl?: string; layoutPreviewUrl?: string; layoutOpen?: boolean
  layerInteraction?: { selectedId: string; disabled: boolean; onSelect: (id: string) => void; onMove: (id: string, centerX: number, centerY: number) => void; onScale: (id: string, scale: number) => void }
}) {
  const client = useQueryClient(), lock = useRef(false)
  const [openRevision, setOpenRevision] = useState<number | null>(null)
  const [mode, setMode] = useState<'add' | 'subtract'>('add')
  const [diameter, setDiameter] = useState(32)
  const [tool, setTool] = useState<'brush' | 'sam'>('brush')
  const [label, setLabel] = useState<0 | 1>(1)
  const [freshVersion, setFreshVersion] = useState<string | null>(null)
  const [readyRevision, setReadyRevision] = useState<number | null>(null)
  const [pending, setPending] = useState<SelectionCommand | null>(null)
  const [failed, setFailed] = useState<{ body: SelectionCommand; error: unknown } | null>(null)
  const key = selectionKey(userId, row.id, row.revision)
  function expire(error: unknown) {
    if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
  }
  const query = useQuery({ queryKey: key, queryFn: async () => { try { return await selectionApi.get(row.id, row.revision) } catch (error) { expire(error); throw error } }, retry: false, refetchInterval: 5000 })
  const data = query.data, active = openRevision === row.revision && !draftOpen
  const currentPending = pending?.revision === row.revision ? pending : null
  const failure = failed?.body.revision === row.revision ? failed : null
  const prepare = useMutation({ mutationFn: (revision: number) => selectionApi.prepare(row.id, revision), retry: false,
    onSuccess: result => setReadyRevision(result.revision),
    onError: error => { expire(error); if (error instanceof ApiError && error.status === 409) onRefresh() },
  })
  const mutation = useMutation({ mutationFn: async (body: SelectionCommand) => {
    await client.cancelQueries({ queryKey: selectionKey(userId, row.id, body.revision) })
    return selectionApi.change(row.id, body)
  }, retry: false,
    onSuccess: async (result, body) => {
      const target = selectionKey(userId, row.id, body.revision)
      await client.cancelQueries({ queryKey: target })
      client.setQueryData<SelectionState>(target, previous => previous && previous.version > result.version ? previous : result)
      setPending(value => value?.request_id === body.request_id ? null : value)
      setFailed(null)
    },
    onError: (error, body) => { expire(error); setFailed({ body, error }); void query.refetch(); if (error instanceof ApiError && error.status === 409) onRefresh() },
    onSettled: () => { lock.current = false },
  })
  const blocked = disabled || draftOpen || mutation.isPending || prepare.isPending || query.isPending || query.isError || Boolean(failure)
  const brushSize = Math.min(diameter, row.document.width, row.document.height)
  const fresh = freshVersion === `${row.revision}/${data?.version}`
  const prompts = currentPending && 'prompts' in currentPending ? currentPending.prompts : fresh ? [] : data?.sam_prompts ?? []
  const samReady = readyRevision === row.revision
  function enter(value: 'brush' | 'sam') {
    setTool(value); setOpenRevision(row.revision)
    if (value === 'sam' && !samReady && !prepare.isPending) prepare.mutate(row.revision)
  }
  function point([x, y]: SelectionPoint) {
    if (!data || blocked || !samReady || prompts.length >= 20 || label === 0 && prompts.length === 0) return
    submit({ revision: row.revision, version: data.version, request_id: crypto.randomUUID(), prompts: [...prompts, { x, y, label }] })
  }
  function submit(body: SelectionCommand) {
    if (lock.current || disabled || draftOpen) return
    lock.current = true; setPending(body); setFailed(null); mutation.mutate(body)
  }
  function action(value: 'undo' | 'redo' | 'clear') {
    if (!data || blocked) return
    submit({ revision: row.revision, version: data.version, request_id: crypto.randomUUID(), action: value })
  }
  function stroke(value: SelectionStroke) {
    if (!data || blocked) return
    submit({ ...value, revision: row.revision, version: data.version, request_id: crypto.randomUUID() })
  }
  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (!active || event.defaultPrevented) return
      if (event.key === 'Escape') { setOpenRevision(null); event.preventDefault(); return }
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable=true]')) return
      const undo = event.key.toLowerCase() === 'z' && !event.shiftKey
      const redo = event.key.toLowerCase() === 'y' || event.key.toLowerCase() === 'z' && event.shiftKey
      if (!undo && !redo) return
      if (blocked) { event.preventDefault(); return }
      if (undo ? data?.can_undo : data?.can_redo) { event.preventDefault(); action(undo ? 'undo' : 'redo') }
    }
    window.addEventListener('keydown', keyboard, true)
    return () => window.removeEventListener('keydown', keyboard, true)
  })
  const selectionControls = <details className="selection-toolbox" onToggle={event => { if (!event.currentTarget.open) setOpenRevision(null) }} onKeyDown={event => {
    if (event.key === 'Escape') { event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus() }
  }}><summary>区域修图</summary><div className="selection-toolbox-body">
    <section className={`selection-panel ${active ? 'is-selecting' : ''}`} aria-label="区域选择" data-selection-version={data?.version} data-revision={row.revision}>
      <div className="selection-heading"><h3><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m14 4 6 6M7 17 19 5a2 2 0 0 0-3-3L4 14m0 0-2 8 8-2-6-6Z"/></svg>区域选择</h3>
        <div className="selection-entry">{active ? <button className="primary" type="button" disabled={mutation.isPending || prepare.isPending} onClick={() => setOpenRevision(null)}>完成选区</button> : <><button className="secondary" type="button" disabled={blocked} onClick={() => enter('brush')}>笔刷选区</button><button className="primary" type="button" disabled={blocked} onClick={() => enter('sam')}>智能点选</button></>}</div></div>
      <p className="selection-note">蓝色区域表示选中，不会修改原图。选区临时保存 24 小时，画布编辑后失效。</p>
      {active && <div className="selection-controls">
        <div className="selection-tool-switch" role="group" aria-label="区域选择方式" data-tool={tool}><span className="selection-tool-indicator" aria-hidden="true"/>
          <button type="button" aria-pressed={tool === 'brush'} disabled={blocked} onClick={() => enter('brush')}>笔刷</button><button type="button" aria-pressed={tool === 'sam'} disabled={blocked} onClick={() => enter('sam')}>SAM 点选</button></div>
        {tool === 'brush' ? <>
        <div className="selection-modes" role="group" aria-label="选区笔刷方式"><button className="secondary" type="button" aria-pressed={mode === 'add'} disabled={blocked} onClick={() => setMode('add')}>涂抹选区</button><button className="secondary" type="button" aria-pressed={mode === 'subtract'} disabled={blocked || !data?.has_selection} onClick={() => setMode('subtract')}>擦除选区</button></div>
        <label htmlFor="selection-diameter">笔刷直径 <output>{brushSize} px</output><input id="selection-diameter" type="range" min="2" max={Math.min(256, row.document.width, row.document.height)} step="2" value={brushSize} disabled={blocked} onChange={event => setDiameter(Number(event.target.value))}/></label>
        </> : <div className="sam-controls" aria-busy={prepare.isPending || mutation.isPending}>
          <div className="selection-modes" role="group" aria-label="智能点选标记"><button className="secondary sam-positive" type="button" aria-pressed={label === 1} disabled={blocked} onClick={() => setLabel(1)}>＋ 保留点</button><button className="secondary sam-negative" type="button" aria-pressed={label === 0} disabled={blocked || prompts.length === 0} onClick={() => setLabel(0)}>− 排除点</button><button className="text-button" type="button" disabled={blocked || prompts.length === 0} onClick={() => { setFreshVersion(`${row.revision}/${data?.version}`); setLabel(1) }}>重新点选</button></div>
          <p className="selection-note">{prepare.isPending ? '正在准备本地模型与图片特征，首次可能需要一些时间…' : samReady ? `点击物体内部保留，点选多余部分排除。已用 ${prompts.length}/20 个点；本轮点选替换当前选区，可撤销。` : '图片特征尚未准备好，现有选区仍保留。'}</p>
          {prepare.isError && <div className="selection-error error-message" role="alert"><p>{errorMessage(prepare.error)}</p><button className="secondary" type="button" disabled={prepare.isPending || disabled || draftOpen} onClick={() => prepare.mutate(row.revision)}>重试准备点选</button></div>}
        </div>}
        <div className="selection-actions"><button className="secondary" type="button" disabled={blocked || !data?.can_undo} onClick={() => action('undo')}>撤销选区</button><button className="secondary" type="button" disabled={blocked || !data?.can_redo} onClick={() => action('redo')}>重做选区</button><button className="text-button" type="button" disabled={blocked || !data?.has_selection} onClick={() => action('clear')}>清除选区</button></div>
      </div>}
      <div className="selection-footer"><span role="status">{mutation.isPending ? currentPending && 'prompts' in currentPending ? '正在识别物体并保存选区…' : '正在保存选区…' : data?.has_selection ? `已选中 ${(100 * data.selected_pixels / data.width / data.height).toFixed(1)}% · 选区版本 ${data.version}` : '尚未选择区域'}</span><button className="text-button" type="button" disabled={query.isFetching || mutation.isPending || prepare.isPending} onClick={() => { void query.refetch() }}>重新读取选区</button></div>
      {(failure || query.isError) && <div className="selection-error error-message" role="alert"><p>{errorMessage(failure?.error ?? query.error)}。画布与原图未改动。</p>{failure && <><button className="secondary" type="button" disabled={disabled || draftOpen || mutation.isPending} onClick={() => submit(failure.body)}>重试保存选区</button><button className="text-button" type="button" disabled={query.isFetching || mutation.isPending} onClick={async () => { const result = await query.refetch(); if (result.isSuccess) { setFailed(null); setPending(null) } }}>读取后继续</button></>}</div>}
      {draftOpen && <p className="selection-note">先应用或取消当前预览，再调整选区。</p>}
    </section>
    <PromotePanel key={`promote-${row.id}`} row={row} userId={userId} disabled={disabled} draftOpen={draftOpen} selection={mutation.isPending || prepare.isPending || failure || query.isError ? undefined : data} onRefresh={() => { onRefresh(); void query.refetch() }}/>
    <RegionPanel key={`region-${row.id}`} id={row.id} revision={row.revision} width={row.document.width} height={row.document.height} userId={userId} disabled={disabled} draftOpen={draftOpen} selection={mutation.isPending || prepare.isPending || failure || query.isError ? undefined : data} onRefresh={() => { onRefresh(); void query.refetch() }}/>
    </div></details>
  return <EditorCanvas toolbarExtra={selectionControls} row={row} userId={userId} onRefresh={onRefresh} cropPreview={cropPreview} colorPreviewUrl={colorPreviewUrl} layoutPreviewUrl={layoutPreviewUrl} layoutOpen={layoutOpen} layerInteraction={layerInteraction}
      selection={{ active, disabled: blocked || tool === 'sam' && !samReady, tool, samPoints: prompts, onPoint: point, radius: brushSize / 2, mode, overlayUrl: active && data?.has_selection ? selectionApi.mask(row.id, row.revision, data.version) : undefined,
        pendingStroke: currentPending && 'points' in currentPending ? currentPending : undefined, onStroke: stroke }}/>
}
