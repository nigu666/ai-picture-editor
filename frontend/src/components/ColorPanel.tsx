import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { advancedColorControls, allColorControls, balanceColors, basicColors, colorPreview, colorValue, detailColors, expressionColors, finishColors, neutralColors, normalizeColors, toneColors, type ColorControl, type ColorSettings } from '@/api/colors'
import { ApiError } from '@/api/client'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'

export type ColorPreviewState = { id: string; revision: number; url: string } | null

export default function ColorPanel({ id, revision, saved, disabled, onPreview, onStale, onApply, onClose }: {
  id: string; revision: number; saved: Partial<ColorSettings>; disabled: boolean
  onPreview: (value: ColorPreviewState) => void; onStale: () => unknown
  onApply: (value: ColorSettings) => void; onClose: () => void
}) {
  const client = useQueryClient()
  const baseline = normalizeColors(saved)
  const [values, setValues] = useState<ColorSettings>(() => normalizeColors(saved))
  const [expanded, setExpanded] = useState(() => advancedColorControls.some(({ name }) => baseline[name] !== neutralColors[name]))
  const [ready, setReady] = useState('')
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const blob = useRef<string | null>(null)
  const key = JSON.stringify(values)
  const dirty = allColorControls.some(({ name }) => values[name] !== baseline[name])
  const problem = error?.key === key ? error.message : null
  useEffect(() => () => { onPreview(null); if (blob.current) URL.revokeObjectURL(blob.current) }, [onPreview])
  useEffect(() => {
    if (!dirty) { onPreview(null); return }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const data = await colorPreview(id, revision, JSON.parse(key), controller.signal)
        if (controller.signal.aborted) return
        const url = URL.createObjectURL(data)
        const old = blob.current
        blob.current = url
        onPreview({ id, revision, url }); setReady(key); setError(null)
        if (old) URL.revokeObjectURL(old)
      } catch (cause) {
        if (controller.signal.aborted) return
        setError({ key, message: errorMessage(cause) })
        if (cause instanceof ApiError && cause.status === 401) void client.invalidateQueries({ queryKey: ME_KEY })
        if (cause instanceof ApiError && cause.status === 409) onStale()
      }
    }, 350)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [id, revision, key, dirty, attempt, onPreview, onStale, client])
  function sliders(controls: ColorControl[]) {
    return <div className="color-sliders">{controls.map(control => <div className="color-control" key={control.name}>
      <label htmlFor={`color-${control.name}`}>{control.label}</label><output htmlFor={`color-${control.name}`}>{colorValue(control, values[control.name])}</output>
      <input id={`color-${control.name}`} type="range" min={control.min} max={control.max} step="1" value={Math.round(values[control.name] * 100)} disabled={disabled}
        aria-valuetext={colorValue(control, values[control.name])}
        onChange={event => setValues(previous => ({ ...previous, [control.name]: Number(event.target.value) / 100 }))} />
      <span>{control.left}</span><span>{control.right}</span></div>)}</div>
  }
  return <div className="color-panel" aria-label="调色设置">
    <div className="color-panel-heading"><div><strong>调色</strong><p>预览未保存，应用后可撤销。</p></div>
      <button type="button" className="text-button" disabled={disabled} onClick={() => setValues({ ...neutralColors })}>恢复原始色彩</button></div>
    <div className="color-group-heading"><h4>基础调整</h4><span>100% 为原始值</span></div>
    {sliders(basicColors)}
    <details className="color-advanced" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
      <summary><span>高级调色</span><span className="advanced-description">明暗、白平衡与细节</span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m5 8 5 5 5-5" /></svg></summary>
      <div className="color-advanced-body">
        <div className="color-group-heading"><h4>明暗区域</h4><span>0 为不变</span></div>{sliders(toneColors)}
        <div className="color-group-heading"><h4>白平衡</h4><span>0 为不变</span></div>{sliders(balanceColors)}
        <div className="color-group-heading"><h4>色彩表现</h4><span>优先调整较淡的颜色</span></div>{sliders(expressionColors)}
        <div className="color-group-heading"><h4>细节</h4><span>锐化100%、清晰度0为不变</span></div>{sliders(detailColors)}
        <div className="color-group-heading"><h4>画面收尾</h4><span>暗角0为不变</span></div>{sliders(finishColors)}
      </div>
    </details>
    <div className="color-panel-footer"><p role="status">{problem ? '预览未完成' : !dirty ? '参数与已保存画面一致' : ready === key ? '预览就绪 · 尚未保存' : '正在更新预览…'}</p>
      <div className="color-actions"><button type="button" className="secondary" disabled={disabled} onClick={onClose}>取消调色</button>
        <button type="button" className="primary" disabled={disabled || !dirty || ready !== key || Boolean(problem)} onClick={() => onApply(values)}>{disabled ? '正在保存…' : '应用调色'}</button></div></div>
    {problem && <div className="error-message" role="alert">{problem}<button type="button" className="text-button" disabled={disabled} onClick={() => { setError(null); setReady(''); setAttempt(value => value + 1) }}>重试预览</button></div>}
  </div>
}
