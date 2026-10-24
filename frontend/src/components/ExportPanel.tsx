import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import type { User } from '@/api/auth'
import { deliverySizes, exportCanvas, type BundleOptions, type DeliveryRatio, type ExportOptions } from '@/api/exports'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'

export default function ExportPanel({ id, revision, width, height, userId, disabled, draftOpen, onRefresh, compact = false }: {
  id: string; revision: number; width: number; height: number; userId: string
  disabled: boolean; draftOpen: boolean; onRefresh: () => unknown
  compact?: boolean
}) {
  const client = useQueryClient()
  const controller = useRef<AbortController | null>(null)
  const disclosure = useRef<HTMLDetailsElement>(null)
  const [options, setOptions] = useState<ExportOptions>({ format: 'png', jpeg_quality: 92, background: '#ffffff' })
  const [mode, setMode] = useState<'single' | 'bundle'>('single')
  const [bundle, setBundle] = useState<BundleOptions>({ ratios: ['1:1', '4:5', '9:16'], include_original: true, allow_upscale: false })
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const [problem, setProblem] = useState('')
  useEffect(() => () => { controller.current?.abort() }, [])
  useEffect(() => {
    function dismiss(event: PointerEvent) {
      if (compact && disclosure.current?.open && event.target instanceof Node && !disclosure.current.contains(event.target)) disclosure.current.open = false
    }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [compact])

  async function download() {
    if (controller.current || disabled || draftOpen || (mode === 'bundle' && !bundle.ratios.length)) return
    const request = new AbortController()
    controller.current = request
    setPending(true); setProblem(''); setMessage('')
    try {
      const result = await exportCanvas(id, revision, options, request.signal, mode === 'bundle' ? bundle : undefined)
      if (request.signal.aborted) return
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = result.filename
      document.body.append(anchor)
      anchor.click(); anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setMessage(`已交给浏览器下载：${result.filename}`)
    } catch (error) {
      if (request.signal.aborted) return
      setProblem(errorMessage(error))
      if (error instanceof ApiError && error.status === 409) void onRefresh()
      if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
    } finally {
      if (!request.signal.aborted) { setPending(false); controller.current = null }
    }
  }

  return <details ref={disclosure} className={`background-panel${compact ? ' export-popover' : ''}`} onKeyDown={event => {
    if (event.key === 'Escape') { event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus() }
  }}>
    <summary><span className="background-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" /></svg>导出成品</span>{!compact && <span className="background-badge">原尺寸 / 多尺寸 · 本地处理</span>}<span className="background-chevron" aria-hidden="true">⌄</span></summary>
    <div className="background-body">
      <p className="background-note">导出已保存的可见画面（含文字与图层效果），尺寸 {width} × {height} px；不包含选区标记、视口缩放或未采用候选。下载为合成图片。</p>
      <fieldset className="text-style-row" style={{ border: 0, padding: 0, margin: '12px 0', minWidth: 0 }} disabled={disabled || draftOpen || pending}>
        <legend className="sr-only">成品导出设置</legend>
        <label>导出方式<select value={mode} onChange={event => { setMode(event.target.value as 'single' | 'bundle'); setMessage(''); setProblem('') }}><option value="single">单张 · 当前画布原尺寸</option><option value="bundle">多尺寸 · ZIP打包下载</option></select></label>
        <label>文件格式<select value={options.format} onChange={event => { setMessage(''); setOptions({ ...options, format: event.target.value as ExportOptions['format'], jpeg_quality: Number.isInteger(options.jpeg_quality) && options.jpeg_quality >= 50 && options.jpeg_quality <= 100 ? options.jpeg_quality : 92 }) }}>
          <option value="png">PNG · 无损，保留透明背景</option><option value="jpeg">JPG · 压缩，合成背景色</option>
        </select></label>
        {mode === 'bundle' && <div style={{ gridColumn: '1 / -1' }}>
          <fieldset style={{ border: 0, padding: 0, margin: '8px 0 12px', minWidth: 0 }}><legend>选择输出比例</legend>
            <div className="text-style-row">{(Object.keys(deliverySizes) as DeliveryRatio[]).map(ratio => <label key={ratio} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <input type="checkbox" style={{ width: 'auto', minHeight: 0 }} checked={bundle.ratios.includes(ratio)} onChange={event => { setMessage(''); setBundle({ ...bundle, ratios: event.target.checked ? [...bundle.ratios, ratio] : bundle.ratios.filter(value => value !== ratio) }) }} />
              {ratio} · {deliverySizes[ratio][0]} × {deliverySizes[ratio][1]}
            </label>)}</div>
          </fieldset>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, fontSize: 13 }}><input type="checkbox" style={{ width: 'auto', minHeight: 0 }} checked={bundle.include_original} onChange={event => setBundle({ ...bundle, include_original: event.target.checked })} />同时包含当前画布原尺寸图片</label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}><input type="checkbox" style={{ width: 'auto', minHeight: 0 }} checked={bundle.allow_upscale} onChange={event => setBundle({ ...bundle, allow_upscale: event.target.checked })} />允许放大小图以适配画幅</label>
          <p className="background-note" role="status">{bundle.ratios.length ? `将打包${bundle.ratios.length + Number(bundle.include_original)}张图片和1份尺寸清单。` : '请至少选择一个输出比例。'} 等比缩放完整画布并居中留白，不裁切，不调用AI补全；放大不会增加真实细节。PNG留白透明，JPG使用所选背景色。</p>
        </div>}
        {options.format === 'jpeg' && <>
          <label>背景色 <input type="color" value={options.background} onChange={event => setOptions({ ...options, background: event.target.value })} /> {options.background.toUpperCase()}</label>
          <label>JPG质量（50～100）<input type="number" min={50} max={100} step={1} value={Number.isFinite(options.jpeg_quality) ? options.jpeg_quality : ''} onChange={event => setOptions({ ...options, jpeg_quality: event.target.valueAsNumber })} /></label>
          <p className="background-note">JPG不支持透明；透明部分使用所选背景色。压缩会改变像素，默认质量92。</p>
        </>}
        <button className="secondary" type="button" disabled={(mode === 'bundle' && !bundle.ratios.length) || (options.format === 'jpeg' && (!Number.isInteger(options.jpeg_quality) || options.jpeg_quality < 50 || options.jpeg_quality > 100))} onClick={() => { void download() }}>{pending ? '正在准备文件…' : mode === 'bundle' ? '下载多尺寸ZIP' : `下载 ${options.format === 'png' ? 'PNG' : 'JPG'}`}</button>
      </fieldset>
      {draftOpen && <p className="background-note" role="status">请先应用或退出当前预览，再导出已保存画布。</p>}
      {problem && <p className="error-message" role="alert">{problem}</p>}
      {message && <p className="background-note" role="status">{message}</p>}
    </div>
  </details>
}
