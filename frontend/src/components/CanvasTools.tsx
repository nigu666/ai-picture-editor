import { cropRatios, operationLabels, type CropRatio, type TransformOperation } from '@/api/canvas'

function Icon({ operation }: { operation: TransformOperation | 'crop' | 'color' | 'layout' }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {operation === 'flip_horizontal' ? <><path d="M12 3v18M4 7v10l5-5-5-5Zm16 0v10l-5-5 5-5Z" /></>
      : operation === 'flip_vertical' ? <><path d="M3 12h18M7 4h10l-5 5-5-5Zm0 16h10l-5-5-5 5Z" /></>
      : operation === 'crop' ? <><path d="M7 3v14h14M3 7h14v14M10 7h7M7 10v7" /></>
      : operation === 'color' ? <><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="2.5" fill="white" /><circle cx="15" cy="17" r="2.5" fill="white" /></>
      : operation === 'layout' ? <><path d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5" /><rect x="8" y="8" width="8" height="8" rx="1" /></>
      : <g transform={operation === 'rotate_left' ? 'translate(24 0) scale(-1 1)' : undefined}><path d="M6 7a7 7 0 1 1-1 9M6 3v4H2" /></g>}
  </svg>
}

export default function CanvasTools({ disabled, crop, setCrop, apply, transform, previewSize, colorOpen, toggleColor, layoutOpen, toggleLayout }: {
  disabled: boolean; crop: CropRatio | null; setCrop: (value: CropRatio | null) => void
  apply: () => void; transform: (value: TransformOperation) => void; previewSize: string | null
  colorOpen: boolean; toggleColor: () => void
  layoutOpen: boolean; toggleLayout: () => void
}) {
  return <div className="canvas-tools" aria-label="本地编辑工具">
    <div className="canvas-tool-buttons" role="toolbar" aria-label="翻转旋转与裁剪">
      {(Object.keys(operationLabels) as TransformOperation[]).map(operation => <button key={operation} type="button" className="secondary canvas-tool-button"
        title={operationLabels[operation]} disabled={disabled || crop !== null || colorOpen || layoutOpen} onClick={() => transform(operation)}><Icon operation={operation} /><span>{operationLabels[operation]}</span></button>)}
      <button type="button" className={`secondary canvas-tool-button ${layoutOpen ? 'tool-active' : ''}`} disabled={disabled}
        aria-expanded={layoutOpen} onClick={toggleLayout}><Icon operation="layout" /><span>位置与大小</span></button>
      <button type="button" className={`secondary canvas-tool-button ${crop ? 'tool-active' : ''}`} disabled={disabled}
        aria-expanded={crop !== null} onClick={() => setCrop(crop ? null : '1:1')}><Icon operation="crop" /><span>裁剪</span></button>
      <button type="button" className={`secondary canvas-tool-button ${colorOpen ? 'tool-active' : ''}`} disabled={disabled}
        aria-expanded={colorOpen} onClick={toggleColor}><Icon operation="color" /><span>调色</span></button>
    </div>
    <a className="toolrail-more" href="#image-tools">更多工具<span aria-hidden="true">↓</span></a>
    {crop && <div className="crop-panel" aria-label="居中裁剪设置">
      <div className="crop-options"><label htmlFor="crop-ratio">居中裁剪</label><select id="crop-ratio" value={crop} disabled={disabled} onChange={e => setCrop(e.target.value as CropRatio)}>
        {cropRatios.map(value => <option key={value} value={value}>{value}</option>)}</select>
        <span className={previewSize ? 'crop-size' : 'crop-size is-invalid'} role="status">{previewSize ? `裁剪后 ${previewSize}` : '裁剪区域最短边需达到 32 px'}</span></div>
      <div className="crop-actions"><button type="button" className="secondary" disabled={disabled} onClick={() => setCrop(null)}>取消裁剪</button>
        <button type="button" className="primary" disabled={disabled || !previewSize} onClick={apply}>应用裁剪</button></div>
      <p>亮区会保留。应用前只是预览，可按 Esc 取消；原图保留，可撤销。</p>
    </div>}
  </div>
}
