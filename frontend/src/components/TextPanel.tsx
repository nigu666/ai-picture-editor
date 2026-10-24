import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import { textApi, type AddText, type OcrBox, type TextInput } from '@/api/text'
import type { EditSession } from '@/api/sessions'
import type { User } from '@/api/auth'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'

export default function TextPanel({ row, userId, selectedId, disabled, draftOpen, onBusy, onRefresh }: {
  row: EditSession; userId: string; selectedId: string; disabled: boolean; draftOpen: boolean
  onBusy: (value: boolean) => void; onRefresh: () => void
}) {
  const client = useQueryClient(), request = useRef<{ signature: string; body: AddText } | null>(null), lock = useRef(false)
  const [boxes, setBoxes] = useState<OcrBox[]>([]), [chosen, setChosen] = useState<string[]>([]), [detectedRevision, setDetectedRevision] = useState<number | null>(null)
  const [manual, setManual] = useState(''), [fill, setFill] = useState('#172b43'), [fontSize, setFontSize] = useState('32')
  const current = row.document.layers.find(layer => layer.id === selectedId)
  function expire(error: unknown) { if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null) }
  const options = useQuery({ queryKey: ['text-options', userId, row.id], queryFn: async () => { try { return await textApi.options(row.id) } catch (error) { expire(error); throw error } }, retry: false })
  const recognize = useMutation({ mutationFn: () => textApi.recognize(row.id, row.revision), retry: false,
    onSuccess: result => { setBoxes(result.boxes); setChosen([]); setDetectedRevision(result.revision) },
    onError: error => { expire(error); if (error instanceof ApiError && error.status === 409) onRefresh() } })
  function saved(result: EditSession) {
    client.setQueryData(['edit-session', userId, row.id], result)
    void client.invalidateQueries({ queryKey: ['sessions', userId] }); onRefresh()
  }
  const add = useMutation({ mutationFn: (body: AddText) => textApi.add(row.id, body), retry: false,
    onSuccess: result => { saved(result); request.current = null; setManual(''); setChosen([]) },
    onError: error => { expire(error); onRefresh() }, onSettled: () => { lock.current = false } })
  const remove = useMutation({ mutationFn: (id: string) => textApi.remove(row.id, id, row.revision), retry: false,
    onSuccess: saved, onError: error => { expire(error); onRefresh() }, onSettled: () => { lock.current = false } })
  const busy = recognize.isPending || add.isPending || remove.isPending
  useEffect(() => { onBusy(busy); return () => onBusy(false) }, [busy, onBusy])
  const blocked = disabled || draftOpen || busy
  const stale = detectedRevision !== null && detectedRevision !== row.revision
  const available = 20 - row.document.layers.length
  const selected = boxes.filter(box => chosen.includes(box.id)), validSize = Number.isInteger(Number(fontSize)) && +fontSize >= 6 && +fontSize <= 512
  const canAdd = options.data?.text_enabled && available > 0
  function submit(layers: TextInput[]) {
    if (lock.current || blocked || !canAdd || layers.length === 0 || layers.length > available || layers.some(layer => !layer.text.trim())) return
    const signature = JSON.stringify([row.revision, layers])
    if (request.current?.signature !== signature) request.current = { signature, body: { revision: row.revision, request_id: crypto.randomUUID(), layers } }
    lock.current = true; add.mutate(request.current.body)
  }
  function addManual() {
    if (!manual.trim() || !validSize) return
    const x = Math.round(row.document.width * 0.08), y = Math.round(row.document.height * 0.08)
    submit([{ text: manual, fill, font_size: +fontSize, x, y, width: Math.max(1, Math.min(1600, row.document.width - x)), height: Math.max(1, Math.min(400, row.document.height - y)) }])
  }
  const problem = remove.error ?? add.error ?? recognize.error ?? options.error
  return <details className="background-panel text-panel" data-text-revision={detectedRevision ?? ''}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7V4h16v3M12 4v16m-4 0h8"/></svg>文字识别与文字层</span><span className="background-badge">本地识别 · 可编辑</span><span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body">
      <p className="background-intro">识别当前可见画面，校对并勾选需要的文字，再明确添加图层。也可以直接写入新文字。</p>
      <p className="text-source-note">新增文字不会擦除底图原字。在原位置添加可能重叠；可移动新文字，或在添加文字层前处理底图原字。</p>
      <div className="text-ocr-toolbar"><span>{recognize.isPending ? '正在本地识别，首次可能稍慢…' : '中英文识别 · 不调用云端模型'}</span><button className="secondary" type="button" disabled={blocked || !options.data?.ocr_enabled} onClick={() => recognize.mutate()}>{recognize.isPending ? '识别中…' : '识别画面文字'}</button></div>
      {options.data && !options.data.ocr_enabled && <p className="background-note">OCR未启用或本地模型不完整，可以手动添加文字。</p>}
      {options.data && !options.data.text_enabled && <p className="error-message" role="alert">缺少本地微软雅黑字体，暂不能添加或预览文字层。</p>}
      {detectedRevision !== null && <div className="text-ocr-result"><div className="text-result-heading"><strong>识别到 {boxes.length} 行</strong><span>已选 {selected.length} · 可再添加 {available} 层</span></div>
        {boxes.length === 0 && <p className="background-note">未识别到可用文字，可以手动输入。识别未修改画布。</p>}
        {recognize.data?.truncated && <p className="background-note">识别行数较多，当前只展示前100行。</p>}
        {stale && <p className="background-note" role="status">画布修订已变化，请重新识别再添加，旧坐标不会直接写入新画布。</p>}
        <div className="text-ocr-list">{boxes.map(box => <div key={box.id} className="text-ocr-item"><label className="text-ocr-check"><input type="checkbox" checked={chosen.includes(box.id)} disabled={blocked || stale} onChange={event => setChosen(previous => event.target.checked ? [...previous, box.id] : previous.filter(id => id !== box.id))}/><span>选择 · 可信度 {Math.round(box.confidence * 100)}%</span><small>{box.x}, {box.y} · {box.width}×{box.height}</small></label><textarea aria-label={`校对识别文字 ${box.id}`} value={box.text} maxLength={1000} disabled={blocked || stale} onChange={event => setBoxes(previous => previous.map(item => item.id === box.id ? { ...item, text: event.target.value } : item))}/></div>)}</div>
        {boxes.length > 0 && <><p className="background-note">字号与文字框为估算，花字、旋转文字和复杂排版需手动调整。默认不选中，避免重复添加。</p><button className="primary" type="button" disabled={blocked || stale || !canAdd || !selected.length || selected.length > available || selected.some(box => !box.text.trim())} onClick={() => submit(selected.map(({ text, x, y, width, height, font_size }) => ({ text, x, y, width, height, font_size, fill })))}>{add.isPending ? '正在保存文字层…' : `添加所选 ${selected.length} 行文字`}</button></>}
      </div>}
      <form className="text-manual-form" onSubmit={event => { event.preventDefault(); addManual() }}><label htmlFor={`manual-text-${row.id}`}>手动添加文字<textarea id={`manual-text-${row.id}`} value={manual} maxLength={1000} disabled={blocked} placeholder="输入标题、标注或修正后的文字" onChange={event => setManual(event.target.value)}/></label><div className="text-style-row"><label htmlFor={`new-text-size-${row.id}`}>字号<input id={`new-text-size-${row.id}`} type="number" min="6" max="512" step="1" value={fontSize} disabled={blocked} onChange={event => setFontSize(event.target.value)}/></label><label htmlFor={`new-text-color-${row.id}`}>文字颜色<input id={`new-text-color-${row.id}`} type="color" value={fill} disabled={blocked} onChange={event => setFill(event.target.value)}/></label></div><button className="primary" type="submit" disabled={blocked || !canAdd || !manual.trim() || !validSize}>添加新文字层</button></form>
      <p className="background-note">添加后，在右侧选择文字层，可修改内容、字号、颜色、对齐和文字框；画布中可移动、缩放，支持撤销。</p>
      {current?.kind === 'text' && <div className="text-remove-row"><span>所选文字：{current.text.slice(0, 24)}</span><button className="text-button" type="button" disabled={blocked} onClick={() => { if (!lock.current) { lock.current = true; remove.mutate(current.id) } }}>删除所选文字层</button></div>}
      {available === 0 && <p className="background-note">已达20层上限，可删除文字层或撤销添加。</p>}
      {draftOpen && <p className="background-note">先应用或取消当前预览，再识别、添加或删除文字。</p>}
      {problem && <p className="error-message" role="alert">{errorMessage(problem)}。请重新读取会话核对，文字草稿仍保留。</p>}
      <div className="background-refresh"><span>字体：{options.data?.font_name ?? '微软雅黑'} · 文字保存在图层文档</span><button className="text-button" type="button" disabled={busy || options.isFetching} onClick={() => { void options.refetch(); onRefresh() }}>重新读取配置与会话</button></div>
    </div>
  </details>
}
