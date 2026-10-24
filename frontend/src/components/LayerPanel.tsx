import { useCallback, useRef, useState } from 'react'
import type { EditSession } from '@/api/sessions'
import type { LayerCanvasDraft, LayerEdit } from '@/api/layerControls'
import type { ColorPreviewState } from './ColorPanel'
import LayerProperties from './LayerProperties'

export default function LayerPanel({ row, selectedId, canvasMove, disabled, retrying, onSelect, onAdd, onEdit, onPreview, onDraft, onStale, onCancelMove }: {
  row: EditSession; selectedId: string; canvasMove: LayerCanvasDraft | null; disabled: boolean; retrying: boolean
  onSelect: (id: string) => void
  onAdd: (body: { revision: number; asset_id: string; request_id: string }, onSuccess: () => void) => void
  onEdit: (params: LayerEdit) => void; onPreview: (value: ColorPreviewState) => void; onDraft: (value: boolean) => void; onStale: () => unknown; onCancelMove: () => void
}) {
  const [source, setSource] = useState(''), [editing, setEditing] = useState(false)
  const draft = useCallback((value: boolean) => { setEditing(value); onDraft(value) }, [onDraft])
  const request = useRef<{ revision: number; asset_id: string; request_id: string } | null>(null)
  const layers = row.document.layers, count = layers.length
  const current = layers.find(layer => layer.id === selectedId) ?? [...layers].reverse().find(layer => layer.visible && !layer.locked) ?? layers[count - 1]
  const index = layers.findIndex(layer => layer.id === current.id)
  function add() {
    if (disabled || editing || !source || count >= 20) return
    if (!request.current || request.current.asset_id !== source) request.current = { revision: row.revision, asset_id: source, request_id: crypto.randomUUID() }
    onAdd(request.current, () => { request.current = null; setSource('') })
  }
  return <section className="layer-panel" aria-label="图层面板" data-layer-count={count} data-selected-layer={current.id}>
    <div className="panel-heading"><h3><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" /></svg>图层</h3><span>{count} / 20</span></div>
    <details className="layer-help"><summary>图层操作说明</summary>    <p className="panel-note">上方覆盖下方。画布点击边界选层，拖动未锁定图层或其右下角圆点改变大小；松开后先预览再应用。透明处仍按矩形边界命中。</p></details>
    <ol className="layer-list" aria-label="图层顺序，从顶层到底层">{[...layers].reverse().map((layer, at) => {
      const asset = row.assets.find(asset => asset.id === layer.asset_id), name = layer.name ?? '图片图层'
      return <li key={layer.id} data-layer-id={layer.id} className={layer.id === current.id ? 'is-selected' : ''}>
        <button type="button" className="layer-select" aria-label={`选择图层 ${name}`} aria-pressed={layer.id === current.id} disabled={disabled || editing} onClick={() => onSelect(layer.id)}>
          <span className="layer-thumbnail">{layer.kind === 'text' ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M4 6V4h16v2M12 4v16m-4 0h8"/></svg> : asset && <img src={asset.url} alt="" loading="lazy" />}</span><span className="layer-label"><strong>{layer.kind === 'text' ? layer.text.replace(/\n/g, ' ').slice(0, 20) : name}</strong><span>{layer.kind === 'text' ? '文字 · ' : ''}{at === 0 ? '顶层' : at === count - 1 ? '底层' : `第 ${count - at} 层`} · {layer.visible ? '显示' : '隐藏'} · {Math.round(layer.opacity * 100)}%</span></span>
        </button>
        <button type="button" className="layer-visibility" disabled={disabled || editing} aria-label={`${layer.visible ? '隐藏' : '显示'}图层 ${name}`} title={layer.visible ? '隐藏图层' : '显示图层'} onClick={() => onEdit({ layer_id: layer.id, visible: !layer.visible })}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>{!layer.visible && <path d="m3 3 18 18"/>}</svg></button>
      </li>
    })}</ol>
    <div className="layer-actions"><span>{current.locked ? '位置已锁定' : '位置可调整'}</span><button className="text-button" type="button" disabled={disabled || editing} onClick={() => onEdit({ layer_id: current.id, locked: !current.locked })}>{current.locked ? '解锁位置' : '锁定位置'}</button></div>
    <div className="layer-order" role="group" aria-label="所选图层层序">{[{ label: '置顶', position: count - 1 }, { label: '上移', position: index + 1 }, { label: '下移', position: index - 1 }, { label: '置底', position: 0 }].map(item => <button key={item.label} className="secondary" type="button" disabled={disabled || editing || item.position < 0 || item.position >= count || item.position === index} onClick={() => onEdit({ layer_id: current.id, position: item.position })}>{item.label}</button>)}</div>
    <details className="layer-properties-disclosure" open={canvasMove ? true : undefined}><summary>所选图层属性</summary>
    <LayerProperties key={`${current.id}/${row.revision}/${canvasMove?.layer_id === current.id ? canvasMove.sequence : 0}`} id={row.id} revision={row.revision} layer={current} canvasMove={canvasMove} disabled={disabled} onPreview={onPreview} onDraft={draft} onStale={onStale} onEdit={onEdit} onCancel={onCancelMove}/>
    </details>
    {editing && <p className="panel-note">先应用或取消当前调整，再切换图层。</p>}
    <details className="layer-add-disclosure"><summary>从候选添加图层</summary>
    <form className="layer-add-form" onSubmit={event => { event.preventDefault(); add() }}>
      <label htmlFor="layer-source">从会话候选添加</label>
      <select id="layer-source" value={source} disabled={disabled || editing || count >= 20} onChange={event => { setSource(event.target.value); request.current = null }}><option value="">选择一张图片</option>{row.assets.map((asset, i) => <option key={asset.id} value={asset.id}>候选 {i + 1} · {asset.width} × {asset.height}</option>)}</select>
      <button className="primary" type="submit" disabled={disabled || editing || !source || count >= 20}>{retrying ? '核对并重试添加' : '添加为图片图层'}</button>
    </form>
    </details>
    {count >= 20 && <p className="panel-note" role="status">已达20层上限，可撤销添加或新建会话。</p>}
  </section>
}
