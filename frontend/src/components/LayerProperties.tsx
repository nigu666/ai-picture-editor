import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { layerPreview, layerValues, type ImageLayer, type LayerCanvasDraft, type LayerEdit } from '@/api/layerControls'
import { ApiError } from '@/api/client'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import type { ColorPreviewState } from './ColorPanel'

export default function LayerProperties({ id, revision, layer, canvasMove, disabled, onPreview, onDraft, onStale, onEdit, onCancel }: {
  id: string; revision: number; layer: ImageLayer; canvasMove: LayerCanvasDraft | null; disabled: boolean
  onPreview: (value: ColorPreviewState) => void; onDraft: (value: boolean) => void; onStale: () => unknown; onEdit: (params: LayerEdit) => void; onCancel: () => void
}) {
  const isText = layer.kind === 'text'
  const typography = layer.kind === 'text' ? { text: layer.text, fill: layer.fill, align: layer.align, font_size: layer.font_size } : { text: '', fill: '#172b43', align: 'left' as const, font_size: 32 }
  const client = useQueryClient(), baseline = { ...layerValues(layer), font_size: typography.font_size, width: layer.width, height: layer.height }
  const initial = { center_x: String(+baseline.center_x.toFixed(6)), center_y: String(+baseline.center_y.toFixed(6)), scale: String(+(baseline.scale * 100).toFixed(4)), opacity: String(+(baseline.opacity * 100).toFixed(4)), rotation: String(+baseline.rotation.toFixed(6)), font_size: String(baseline.font_size), width: String(layer.width), height: String(layer.height), text: typography.text, fill: typography.fill, align: typography.align }
  // 外部拖动只作为本次表单草稿初值；父组件通过 key 让新拖动重新初始化表单。
  const movedInitial = canvasMove?.layer_id === layer.id && !layer.locked ?
    { ...initial, ...(canvasMove.center_x === undefined ? {} : { center_x: String(canvasMove.center_x) }),
      ...(canvasMove.center_y === undefined ? {} : { center_y: String(canvasMove.center_y) }),
      ...(canvasMove.scale === undefined ? {} : { scale: String(+(canvasMove.scale * 100).toFixed(4)) }) } : initial
  const [values, setValues] = useState(movedInitial), [attempt, setAttempt] = useState(0)
  const fields = [{ key: 'center_x', label: '中心 X', unit: 'px', min: -100000, max: 100000 }, { key: 'center_y', label: '中心 Y', unit: 'px', min: -100000, max: 100000 }, { key: 'scale', label: '等比缩放', unit: '%', min: 5, max: 400 }, { key: 'rotation', label: '旋转', unit: '°', min: -180, max: 180 }, { key: 'opacity', label: '不透明度', unit: '%', min: 0, max: 100 }, ...(isText ? [{ key: 'font_size', label: '字号', unit: 'px', min: 6, max: 512 }, { key: 'width', label: '文字框宽', unit: 'px', min: 1, max: 4096 }, { key: 'height', label: '文字框高', unit: 'px', min: 1, max: 4096 }] as const : [])] as const
  const integerKeys = new Set(['font_size', 'width', 'height'])
  const numeric = { center_x: Number(values.center_x), center_y: Number(values.center_y), scale: Number(values.scale) / 100, opacity: Number(values.opacity) / 100, rotation: Number(values.rotation), font_size: Number(values.font_size), width: Number(values.width), height: Number(values.height) }
  const valid = fields.every(field => values[field.key].trim() !== '' && Number.isFinite(Number(values[field.key])) && (!integerKeys.has(field.key) || Number.isInteger(Number(values[field.key]))) && +values[field.key] >= field.min && +values[field.key] <= field.max) && (!isText || Boolean(values.text.trim()) && /^#[0-9a-fA-F]{6}$/.test(values.fill) && numeric.width * numeric.height <= 4000000)
  const params: LayerEdit = { layer_id: layer.id }
  for (const field of fields) if (Math.abs(numeric[field.key] - baseline[field.key]) > 1e-5 || values[field.key].trim() === '') params[field.key] = numeric[field.key]
  if (isText) {
    if (values.text !== typography.text) params.text = values.text
    if (values.fill !== typography.fill) params.fill = values.fill
    if (values.align !== typography.align) params.align = values.align
  }
  const dirty = Object.keys(params).length > 1, key = JSON.stringify(params)
  const [ready, setReady] = useState(''), [error, setError] = useState<{ key: string; message: string } | null>(null)
  const problem = error?.key === key ? error.message : null, blob = useRef<string | null>(null)
  useEffect(() => { onDraft(dirty); return () => onDraft(false) }, [dirty, onDraft])
  useEffect(() => () => { onPreview(null); if (blob.current) URL.revokeObjectURL(blob.current) }, [onPreview])
  useEffect(() => {
    onPreview(null)
    if (!dirty || !valid) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const data = await layerPreview(id, revision, JSON.parse(key), controller.signal)
        if (controller.signal.aborted) return
        const url = URL.createObjectURL(data), old = blob.current
        blob.current = url; onPreview({ id, revision, url }); setReady(key); setError(null)
        if (old) URL.revokeObjectURL(old)
      } catch (cause) {
        if (controller.signal.aborted) return
        setError({ key, message: errorMessage(cause) })
        if (cause instanceof ApiError && cause.status === 401) void client.invalidateQueries({ queryKey: ME_KEY })
        if (cause instanceof ApiError && cause.status === 409) onStale()
      }
    }, 350)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [id, revision, key, dirty, valid, attempt, onPreview, onStale, client])
  return <form className="layer-properties" aria-label="所选图层属性" data-layer-draft={dirty} onSubmit={event => { event.preventDefault(); if (!disabled && valid && dirty && ready === key && !problem) onEdit(params) }}>
    <div className="layer-properties-heading"><strong>{layer.name ?? '图片图层'}</strong><span>{layer.locked ? '已锁定位置' : '可调整位置'}</span></div>
    {isText && <div className="text-layer-fields"><label htmlFor={`text-content-${layer.id}`}>文字内容<textarea id={`text-content-${layer.id}`} value={values.text} maxLength={1000} disabled={disabled} onChange={event => setValues(previous => ({ ...previous, text: event.target.value }))}/></label><div className="text-style-row"><label htmlFor={`text-fill-${layer.id}`}>颜色<input id={`text-fill-${layer.id}`} type="color" value={values.fill} disabled={disabled} onChange={event => setValues(previous => ({ ...previous, fill: event.target.value }))}/></label><label htmlFor={`text-align-${layer.id}`}>对齐<select id={`text-align-${layer.id}`} value={values.align} disabled={disabled} onChange={event => setValues(previous => ({ ...previous, align: event.target.value as 'left' | 'center' | 'right' }))}><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></select></label></div><p className="panel-note">微软雅黑 · 按字宽折行，框外内容裁切。可加大文字框；新增文字不擦除底图原字。</p></div>}
    {fields.map(field => <label key={field.key} htmlFor={`layer-${field.key}`} className="layer-value"><span>{field.label}</span><div><input id={`layer-${field.key}`} type="number" step={integerKeys.has(field.key) ? '1' : 'any'} min={field.min} max={field.max} value={values[field.key]} disabled={disabled || layer.locked && field.key !== 'opacity' && field.key !== 'font_size'} aria-invalid={values[field.key].trim() === '' || !Number.isFinite(+values[field.key]) || +values[field.key] < field.min || +values[field.key] > field.max} onChange={event => setValues(previous => ({ ...previous, [field.key]: event.target.value }))}/><span>{field.unit}</span></div></label>)}
    <p className="panel-note" role="status">{!valid ? '请输入有效数值' : problem ? '预览未完成，请重试' : !dirty ? '仅调整所选图层' : ready === key ? '预览就绪 · 尚未保存' : '正在更新预览…'}</p>
    {dirty && <div className="layer-property-actions"><button type="button" className="secondary" disabled={disabled} onClick={() => { setValues(initial); onCancel() }}>取消调整</button><button className="primary" type="submit" disabled={disabled || !valid || !dirty || ready !== key || Boolean(problem)}>应用图层调整</button></div>}
    {problem && <p className="error-message" role="alert">{problem}<button type="button" className="text-button" disabled={disabled} onClick={() => { setReady(''); setError(null); setAttempt(x => x + 1) }}>重试图层预览</button></p>}
  </form>
}
