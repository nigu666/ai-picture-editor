import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { layoutPreview, placementOf, type Placement } from '@/api/layout'
import type { CanvasDocument } from '@/api/sessions'
import { ApiError } from '@/api/client'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import type { ColorPreviewState } from './ColorPanel'

export default function LayoutPanel({ id, revision, document, disabled, onPreview, onStale, onApply, onClose }: {
  id: string; revision: number; document: CanvasDocument; disabled: boolean
  onPreview: (value: ColorPreviewState) => void; onStale: () => unknown
  onApply: (value: Placement) => void; onClose: () => void
}) {
  const client = useQueryClient(), baseline = placementOf(document)
  const [values, setValues] = useState(() => ({ center_x: String(Math.round(baseline.center_x * 1e6) / 1e6), center_y: String(Math.round(baseline.center_y * 1e6) / 1e6), scale: String(Math.round(baseline.scale * 10000) / 100) }))
  const params: Placement = { center_x: Number(values.center_x), center_y: Number(values.center_y), scale: Number(values.scale) / 100 }
  const valid = Object.values(values).every(value => value.trim() !== '' && Number.isFinite(Number(value))) && Math.abs(params.center_x) <= 100000 && Math.abs(params.center_y) <= 100000 && params.scale >= .05 && params.scale <= 4
  const dirty = (Object.keys(params) as (keyof Placement)[]).some(key => Math.abs(params[key] - baseline[key]) > 1e-5)
  const key = JSON.stringify(params)
  const [ready, setReady] = useState(''), [attempt, setAttempt] = useState(0)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const problem = error?.key === key ? error.message : null
  const blob = useRef<string | null>(null)
  useEffect(() => () => { onPreview(null); if (blob.current) URL.revokeObjectURL(blob.current) }, [onPreview])
  useEffect(() => {
    if (!dirty || !valid) { onPreview(null); return }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const data = await layoutPreview(id, revision, JSON.parse(key), controller.signal)
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
  return <div className="layout-panel" aria-label="位置与大小设置">
    <div className="layout-heading"><div><span className="layout-kicker">图片变换</span><h3>位置与大小</h3><p>调整图片本身，画布尺寸保持不变。</p></div><span className="layout-badge">本地预览</span></div>
    <div className="layout-fields">
      {([{ key: 'center_x', label: '中心 X', unit: 'px', min: -100000, max: 100000 }, { key: 'center_y', label: '中心 Y', unit: 'px', min: -100000, max: 100000 }, { key: 'scale', label: '图片缩放', unit: '%', min: 5, max: 400 }] as const).map(field => <label key={field.key} htmlFor={`layout-${field.key}`} className="layout-field"><span>{field.label}</span><div><input id={`layout-${field.key}`} type="number" step="any" min={field.min} max={field.max} value={values[field.key]} disabled={disabled}
        aria-invalid={values[field.key].trim() === '' || !Number.isFinite(Number(values[field.key])) || Number(values[field.key]) < field.min || Number(values[field.key]) > field.max}
        onChange={event => setValues(previous => ({ ...previous, [field.key]: event.target.value }))} /><span>{field.unit}</span></div></label>)}
    </div>
    <div className="layout-shortcuts"><button className="secondary" disabled={disabled} onClick={() => setValues(previous => ({ ...previous, center_x: String(document.width / 2), center_y: String(document.height / 2) }))}>画布居中</button>
      <button className="secondary" disabled={disabled} onClick={() => setValues(previous => ({ ...previous, scale: '100' }))}>原始大小</button><span>保留旋转与翻转方向</span></div>
    <p className="layout-hint">缩放范围 5%–400%。移出画布的部分暂不显示，可居中找回。</p>
    <div className="layout-footer"><p role="status">{!valid ? '请输入有效坐标和缩放比例' : problem ? '预览未完成' : !dirty ? '参数与已保存画面一致' : ready === key ? '预览就绪 · 尚未保存' : '正在更新预览…'}</p>
      <div className="layout-actions"><button type="button" className="secondary" disabled={disabled} onClick={onClose}>取消变换</button><button type="button" className="primary" disabled={disabled || !valid || !dirty || ready !== key || Boolean(problem)} onClick={() => onApply(params)}>{disabled ? '正在保存…' : '应用变换'}</button></div></div>
    {problem && <div className="error-message" role="alert">{problem}<button className="text-button" disabled={disabled} onClick={() => { setError(null); setReady(''); setAttempt(value => value + 1) }}>重试预览</button></div>}
  </div>
}
