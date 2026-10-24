import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import SelectionEditor from './SelectionEditor'
import type { EditorController } from '@/hooks/useEditorSession'
import { errorMessage } from '@/hooks/useAuth'
import { ApiError } from '@/api/client'
import CanvasTools from './CanvasTools'
import { cropBox, operationLabels, type CropRatio } from '@/api/canvas'
import ColorPanel, { type ColorPreviewState } from './ColorPanel'
import { neutralColors } from '@/api/colors'
import MattingPanel from './MattingPanel'
import LayoutPanel from './LayoutPanel'
import BackgroundPanel from './BackgroundPanel'
import OutpaintingPanel from './OutpaintingPanel'
import UpscalingPanel from './UpscalingPanel'
import LayerPanel from './LayerPanel'
import SplitPanel from './SplitPanel'
import TextPanel from './TextPanel'
import ExportPanel from './ExportPanel'
import type { LayerCanvasDraft } from '@/api/layerControls'

const historyLabels: Record<string, string> = { ...operationLabels, add_text_layers: '添加文字图层', remove_text_layer: '删除文字图层', promote_object: '选区成层', edit_layer: '调整图层属性', apply_split_layers: '应用主体与背景拆层', add_image_layer: '添加图片图层', crop_canvas: '按比例裁剪', layout_canvas: '位置与大小', adjust_colors: '调色与细节调整' }

export default function SessionWorkbench({ editor, userId, assistant, onStart }: { editor: EditorController; userId: string; assistant?: ReactNode; onStart?: (view: 'generate' | 'assets') => void }) {
  const row = editor.detail.data
  const host = useRef<HTMLElement>(null)
  const switcher = useRef<HTMLDetailsElement>(null)
  const busy = editor.mutation.isPending
  const [textBusy, setTextBusy] = useState(false)
  const blocked = busy || textBusy || editor.detail.isError || editor.detail.isFetching
  const multi = Boolean(row && row.document.layers.length > 1)
  const [layerDraft, setLayerDraft] = useState(false)
  const [layerPreview, setLayerPreview] = useState<ColorPreviewState>(null)
  const [layerSelection, setLayerSelection] = useState<{ key: string; id: string } | null>(null)
  const [layerCanvasMove, setLayerCanvasMove] = useState<{ id: string; revision: number; value: LayerCanvasDraft } | null>(null)
  const layerSelectionKey = row ? `selected-layer:${userId}:${row.id}` : ''
  let storedLayer: string | null = null
  try { if (row) storedLayer = localStorage.getItem(layerSelectionKey) } catch { /* 无本机存储时仍可选择。 */ }
  const preferredLayer = layerSelection?.key === layerSelectionKey ? layerSelection.id : storedLayer
  const selectedLayerId = row ? (row.document.layers.find(layer => layer.id === preferredLayer)?.id ??
    [...row.document.layers].reverse().find(layer => layer.visible && !layer.locked)?.id ?? row.document.layers[row.document.layers.length - 1].id) : ''
  const canvasMove = row && layerCanvasMove?.id === row.id && layerCanvasMove.revision === row.revision ? layerCanvasMove.value : null
  function selectLayer(id: string) {
    if (!row || layerDraft || blocked) return
    setLayerSelection({ key: layerSelectionKey, id })
    setLayerCanvasMove(null)
    try { localStorage.setItem(layerSelectionKey, id) } catch { /* 本机存储不可用。 */ }
  }
  function moveLayer(layerId: string, centerX: number, centerY: number) {
    if (!row || layerDraft || blocked) return
    setLayerCanvasMove(previous => ({ id: row.id, revision: row.revision, value: {
      layer_id: layerId, center_x: centerX, center_y: centerY, sequence: (previous?.value.sequence ?? 0) + 1,
    } }))
  }
  function scaleLayer(layerId: string, scale: number) {
    if (!row || layerDraft || blocked) return
    setLayerCanvasMove(previous => ({ id: row.id, revision: row.revision, value: {
      layer_id: layerId, scale, sequence: (previous?.value.sequence ?? 0) + 1,
    } }))
  }
  const layerUrl = row && layerPreview?.id === row.id && layerPreview.revision === row.revision ? layerPreview.url : undefined
  const singleBlocked = blocked || multi || layerDraft
  const [draft, setDraft] = useState<{ id: string; value: string } | null>(null)
  const [cropState, setCropState] = useState<{ id: string; revision: number; ratio: CropRatio } | null>(null)
  const [colorState, setColorState] = useState<{ id: string; revision: number } | null>(null)
  const [layoutState, setLayoutState] = useState<{ id: string; revision: number } | null>(null)
  const [layoutPreview, setLayoutPreview] = useState<ColorPreviewState>(null)
  const layoutOpen = Boolean(row && layoutState?.id === row.id && layoutState.revision === row.revision)
  const layoutUrl = row && layoutOpen && layoutPreview?.id === row.id && layoutPreview.revision === row.revision ? layoutPreview.url : undefined
  if (layoutState && layoutState.id !== editor.id) setLayoutState(null)
  const [colorPreview, setColorPreview] = useState<ColorPreviewState>(null)
  const colorOpen = Boolean(row && colorState?.id === row.id && colorState.revision === row.revision)
  const previewUrl = row && colorOpen && colorPreview?.id === row.id && colorPreview.revision === row.revision ? colorPreview.url : undefined
  if (cropState && cropState.id !== editor.id) setCropState(null)
  if (colorState && colorState.id !== editor.id) setColorState(null)
  const crop = row && cropState?.id === row.id && cropState.revision === row.revision ? cropState.ratio : null
  const preview = row && crop ? cropBox(row.document.width, row.document.height, crop) : null
  function setCrop(value: CropRatio | null) {
    setColorState(null); setLayoutState(null)
    if (row) setCropState(value ? { id: row.id, revision: row.revision, ratio: value } : null)
  }
  const title = draft && draft.id === row?.id ? draft.value : row?.title ?? ''
  useEffect(() => { if (editor.id) window.scrollTo({ top: 0, behavior: 'instant' }) }, [editor.id])
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape' && (crop || colorOpen || layoutOpen) && !blocked) { setCropState(null); setColorState(null); setLayoutState(null); return }
      if (!row || blocked || layerDraft || event.defaultPrevented || !(event.ctrlKey || event.metaKey) || event.altKey) return
      if (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable="true"]')) return
      const key = event.key.toLowerCase()
      const redo = key === 'y' || (key === 'z' && event.shiftKey)
      if (key !== 'z' && key !== 'y') return
      event.preventDefault()
      if (redo ? row.can_redo : row.can_undo) editor.change({ action: redo ? 'redo' : 'undo' })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [row, blocked, editor, crop, colorOpen, layoutOpen, layerDraft])
  function rename(event: FormEvent) {
    event.preventDefault()
    if (title.trim()) editor.change({ action: 'rename', body: { title: title.trim() } })
  }
  const saveStatus = <span className="session-save-status" role="status">{layerDraft ? '图层预览未保存' : busy ? '正在保存…' : editor.mutation.isError ? '保存未确认' : row && !editor.detail.isError ? '更改已保存' : '选择图片开始'}</span>
  const sessionPicker = <details className="session-switcher" ref={switcher}><summary aria-label="切换编辑会话" title="切换会话">会话</summary>
      <aside className="session-sidebar" aria-label="编辑会话">
        <div className="panel-heading"><h3>我的会话</h3><button className="text-button" disabled={busy || editor.list.isFetching} onClick={() => { void editor.list.refetch() }}>刷新</button></div>
        <button className="secondary new-session" disabled={busy || layerDraft} onClick={() => { editor.select(null); if (switcher.current) switcher.current.open = false }}>＋ 新建会话</button>
        {editor.list.isPending && <p className="panel-note" role="status">正在读取会话…</p>}
        {editor.list.isError && <p className="error-message" role="alert">{errorMessage(editor.list.error)}，请刷新重试。</p>}
        {editor.list.data?.length === 0 && <p className="panel-note">从素材库或生成结果中选择一张图片。</p>}
        <div className="session-list">{editor.list.data?.map((item) => <button key={item.id}
          className={`session-item ${editor.id === item.id ? 'is-current' : ''}`} disabled={busy || layerDraft}
          aria-pressed={editor.id === item.id} onClick={() => { editor.select(item.id); if (switcher.current) switcher.current.open = false }}>
          <strong>{item.title}</strong><span>修订 {item.revision} · {new Date(item.updated_at).toLocaleDateString('zh-CN')}</span>
        </button>)}</div>
      </aside>
    </details>
  return <section ref={host} className="session-section" aria-labelledby="editor-heading">
    <h2 id="editor-heading" className="sr-only">图片工作台</h2>
    {!row && <div className="workspace-start-row">{sessionPicker}{saveStatus}</div>}
    {editor.mutation.isError && <div className="error-message session-save-error" role="alert"><p>{errorMessage(editor.mutation.error)}
      {!(editor.mutation.error instanceof ApiError) && '；保存结果未确认，请重新读取会话核对，避免重复操作。'}</p>
      <button className="secondary" disabled={editor.detail.isFetching} onClick={() => {
        if (editor.id) void editor.detail.refetch(); else void editor.list.refetch()
      }}>重新读取核对</button></div>}
    <div className="session-workbench">

      {row && !editor.detail.isError && editor.id && <CanvasTools disabled={singleBlocked} crop={crop} setCrop={setCrop}
              layoutOpen={layoutOpen} toggleLayout={() => { setCropState(null); setColorState(null); setLayoutState(layoutOpen ? null : { id: row.id, revision: row.revision }) }}
              colorOpen={colorOpen} toggleColor={() => { setCropState(null); setLayoutState(null); setColorState(colorOpen ? null : { id: row.id, revision: row.revision }) }}
              previewSize={preview ? `${preview.width} × ${preview.height} px` : null}
              transform={operation => editor.tool('transform_canvas', { operation })}
              apply={() => { if (crop) editor.tool('crop_canvas', { ratio: crop }, () => setCropState(null)) }} />}
      <div className="session-main">
        {!editor.id ? <div className="editor-empty"><div className="empty-mark" aria-hidden="true">＋</div><h3>让一张图片成为起点</h3><p>上传素材或生成候选，然后选择“新建编辑会话”。</p><div className="empty-actions"><button type="button" className="primary" onClick={() => onStart?.('assets')}>上传与选择素材</button><button type="button" className="secondary" onClick={() => onStart?.('generate')}>生成一张图片</button></div></div>
          : editor.detail.isError ? <div className="editor-empty" role="alert"><h3>暂时无法读取会话</h3><p>{errorMessage(editor.detail.error)}</p><button className="secondary" onClick={() => { void editor.detail.refetch() }}>重新读取会话</button></div>
          : !row ? <div className="editor-empty" role="status">正在读取画布与编辑记录…</div>
          : <><div className="session-titlebar"><form onSubmit={rename}><label className="sr-only" htmlFor="session-title">会话名称</label>
            <input id="session-title" value={title} maxLength={80} disabled={blocked} onChange={(event) => setDraft({ id: row.id, value: event.target.value })} />
            <button className="text-button" disabled={blocked || !title.trim() || title.trim() === row.title}>保存名称</button></form>
            {saveStatus}{sessionPicker}
            <div className="history-controls"><button className="secondary" title="Ctrl / ⌘ + Z" disabled={blocked || layerDraft || !row.can_undo} onClick={() => editor.change({ action: 'undo' })}>撤销</button>
              <button className="secondary" title="Ctrl / ⌘ + Shift + Z，也可 Ctrl + Y" disabled={blocked || layerDraft || !row.can_redo} onClick={() => editor.change({ action: 'redo' })}>重做</button></div>
            <ExportPanel compact key={`export-${row.id}/${row.revision}`} id={row.id} revision={row.revision} width={row.document.width} height={row.document.height} userId={userId}
              disabled={blocked || editor.mutation.isError} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} onRefresh={editor.detail.refetch} />
            </div>
            {multi && <p className="layer-tool-notice" role="status">多图层生成会先合成当前可见画面（含文字），结果仅进入会话候选，原图层继续保留。明确采用才会替换为单图片画布，可撤销；也可从图层面板添加候选为新层。直接整图裁剪、调色和翻转暂不可用。</p>}


            <SelectionEditor key={row.id} row={row} userId={userId} disabled={blocked || layerDraft} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} cropPreview={preview} colorPreviewUrl={previewUrl} layoutPreviewUrl={layerUrl ?? layoutUrl} layoutOpen={layoutOpen || layerDraft} onRefresh={() => { void editor.detail.refetch() }}
              layerInteraction={{ selectedId: selectedLayerId, disabled: blocked || layerDraft, onSelect: selectLayer, onMove: moveLayer, onScale: scaleLayer }} />
            <div className="session-version"><span>修订 {row.revision}</span>
              <button className="text-button" disabled={blocked} onClick={() => { void editor.detail.refetch() }}>重新读取会话</button></div></>}
      </div>
      {row && !editor.detail.isError && editor.id && <section className="candidate-filmstrip" aria-label="会话候选">
        <div className="panel-heading"><h3>会话候选</h3><span>{row.assets.length} 张</span></div>
        <p className="panel-note">采用会替换画布，可撤销；保留图层用“从候选添加图层”。</p>
        <div className="wall-grid">{row.assets.map((asset, index) => <button key={asset.id} disabled={blocked || layerDraft || (row.current_asset_id === asset.id && !multi)}
          className={`wall-item ${(row.current_asset_id === asset.id && !multi) ? 'is-current' : ''}`}
          aria-label={(row.current_asset_id === asset.id && !multi) ? `候选 ${index + 1}，当前画布` : multi ? `采用候选 ${index + 1}，替换为单图片画布，可撤销` : `采用会话候选 ${index + 1}`}
          onClick={() => editor.change({ action: 'adopt', body: { asset_id: asset.id } })}>
          <img src={asset.url} alt={`会话候选 ${index + 1}`} /><span>{(row.current_asset_id === asset.id && !multi) ? '当前画布' : multi ? `替换为单图 ${index + 1}` : `采用候选 ${index + 1}`}</span></button>)}</div>
      </section>}
      {row && !editor.detail.isError && editor.id && <>
            <div className="workbench-utilities" id="image-tools" aria-label="图片处理工具">
            <SplitPanel key={`split-${row.id}`} id={row.id} revision={row.revision} width={row.document.width} height={row.document.height} userId={userId} disabled={blocked} single={!multi} currentDocument={row.document} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} onRefresh={() => { void editor.detail.refetch(); void editor.list.refetch() }} />
            <TextPanel key={`text-${row.id}`} row={row} userId={userId} selectedId={selectedLayerId} disabled={blocked} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} onBusy={setTextBusy} onRefresh={() => { void editor.detail.refetch(); void editor.list.refetch() }} />
            <details className="background-panel workbench-local-tool"><summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4M7 18c0-4 10-4 10 0"/><circle cx="12" cy="9" r="3"/></svg>去背景</span><span className="background-badge">本地处理</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
            <MattingPanel key={`matting-${row.id}`} id={row.id} revision={row.revision} userId={userId} disabled={blocked || layerDraft} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} onRefresh={editor.detail.refetch} />
            </details>
            <BackgroundPanel key={`background-${row.id}`} id={row.id} revision={row.revision} userId={userId} disabled={blocked || layerDraft} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} onRefresh={editor.detail.refetch} />
            <OutpaintingPanel key={`outpainting-${row.id}`} id={row.id} revision={row.revision} width={row.document.width} height={row.document.height} userId={userId} disabled={blocked || layerDraft} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} onRefresh={editor.detail.refetch} />
            <UpscalingPanel key={`upscaling-${row.id}`} id={row.id} revision={row.revision} width={row.document.width} height={row.document.height} userId={userId} disabled={blocked || layerDraft} draftOpen={Boolean(crop) || colorOpen || layoutOpen || layerDraft} onRefresh={editor.detail.refetch} />
            </div>
      </>}
      {row && !editor.detail.isError && editor.id && <aside className="session-detail" aria-label="图层、AI助手与编辑记录">
            {layoutOpen && <LayoutPanel key={`layout-${row.id}/${row.revision}`} id={row.id} revision={row.revision} document={row.document} disabled={blocked}
              onPreview={setLayoutPreview} onStale={editor.detail.refetch} onClose={() => setLayoutState(null)} onApply={values => editor.tool('layout_canvas', values, () => setLayoutState(null))} />}
            {colorOpen && <ColorPanel key={`${row.id}/${row.revision}`} id={row.id} revision={row.revision}
              saved={row.document.adjustments ?? neutralColors} disabled={blocked} onPreview={setColorPreview} onStale={editor.detail.refetch}
              onClose={() => setColorState(null)} onApply={values => editor.tool('adjust_colors', values, () => setColorState(null))} />}
        <div className="inspector-stack" hidden={colorOpen || layoutOpen}>
        <LayerPanel key={row.id} row={row} selectedId={selectedLayerId} canvasMove={canvasMove} onSelect={selectLayer} onCancelMove={() => setLayerCanvasMove(null)} disabled={blocked || Boolean(crop) || colorOpen || layoutOpen}
          retrying={editor.mutation.isError && editor.mutation.variables?.action === 'layers'}
          onAdd={(body, onSuccess) => editor.change({ action: 'layers', body }, onSuccess)}
          onEdit={params => editor.tool('edit_layer', params)} onPreview={setLayerPreview} onDraft={setLayerDraft} onStale={editor.detail.refetch} />
        {assistant}
        <details className="workbench-history"><summary>编辑记录</summary>
        
        <p className="panel-note">最多保留最近 {row.history_limit} 步。</p>
        <ol className="history-list">{[...row.history].reverse().map((entry) => <li key={entry.seq} className={entry.seq === row.history_seq ? 'is-current' : entry.seq > row.history_seq ? 'is-future' : ''}>
          <span>{entry.seq === row.history_seq ? '●' : '○'}</span><div>{entry.action === 'create_session' ? '创建会话' : historyLabels[entry.action] ?? `采用候选 ${row.assets.findIndex((asset) => asset.id === entry.current_asset_id) + 1}`}<small>第 {entry.seq} 步{entry.seq > row.history_seq ? ' · 可重做' : entry.seq === row.history_seq ? ' · 当前' : ''}</small></div>
        </li>)}</ol>
        </details>
        </div>
      </aside>}
    </div>
  </section>
}
