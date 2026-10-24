import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Stage, Layer, Image as CanvasImage, Group, Line, Rect, Circle } from 'react-konva'
import type { Asset } from '@/api/assets'
import type { CanvasDocument, EditSession } from '@/api/sessions'
import type { CropBox } from '@/api/canvas'
import { useViewport, type Viewport } from '@/stores/viewport'
import { colorSourceUrl } from '@/api/colors'
import type { SelectionDrawing, SelectionPoint } from '@/api/selection'
import type { KonvaEventObject } from 'konva/lib/Node'
import { layerValues } from '@/api/layerControls'

function useImage(url: string | undefined, attempt: number) {
  const [result, setResult] = useState<{ key: string; image?: HTMLImageElement; error: boolean } | null>(null)
  const key = `${url}/${attempt}`
  useEffect(() => {
    if (!url) return
    const image = new window.Image()
    let live = true
    image.crossOrigin = 'anonymous'
    image.onload = () => { if (live) setResult({ key, image, error: false }) }
    image.onerror = () => { if (live) setResult({ key, error: true }) }
    image.src = url
    return () => { live = false; image.onload = null; image.onerror = null }
  }, [url, key])
  return result?.key === key ? result : null
}

function currentAsset(row: EditSession, id: string): Asset | undefined {
  return row.assets.find((asset) => asset.id === id)
}

let pattern: string | undefined
const compositeUrl = (id: string, revision: number, previous = false) => `/api/sessions/${id}/canvas-render?revision=${revision}${previous ? '&previous=true' : ''}`
function previewDocument(document: CanvasDocument, flattened: boolean): CanvasDocument {
  if (!flattened) return document
  return { ...document, layers: [{ ...document.layers[0], kind: 'image', asset_id: document.layers.find(item => item.kind !== 'text')?.asset_id ?? '', width: document.width, height: document.height,
    opacity: 1, visible: true, transform: { x: 0, y: 0, scale_x: 1, scale_y: 1, rotation: 0 } }] }
}
function checkerboard() {
  if (!pattern) {
    const tile = document.createElement('canvas'); tile.width = tile.height = 24
    const ctx = tile.getContext('2d')!
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, 24, 24)
    ctx.fillStyle = '#e1e6ed'; ctx.fillRect(0, 0, 12, 12); ctx.fillRect(12, 12, 12, 12)
    pattern = tile.toDataURL()
  }
  return pattern
}

function DocumentPicture({ document, image, tile }: { document: CanvasDocument; image: HTMLImageElement; tile: HTMLImageElement }) {
  const layer = document.layers[0]
  if (!layer) return null
  const t = layer.transform
  return <Group clipX={0} clipY={0} clipWidth={document.width} clipHeight={document.height}>
    <Rect width={document.width} height={document.height} fill="white" fillPatternImage={tile} fillPriority="pattern" />
    <CanvasImage image={image} width={layer.width} height={layer.height} x={t.x} y={t.y}
      scaleX={t.scale_x} scaleY={t.scale_y} rotation={t.rotation} visible={layer.visible} opacity={layer.opacity} />
  </Group>
}

export default function EditorCanvas({ row, userId, onRefresh, cropPreview, colorPreviewUrl, layoutPreviewUrl, layoutOpen, selection, layerInteraction, toolbarExtra }: {
  row: EditSession; userId: string; onRefresh: () => void; cropPreview?: CropBox | null; colorPreviewUrl?: string; layoutPreviewUrl?: string; layoutOpen?: boolean; selection?: SelectionDrawing
  toolbarExtra?: ReactNode
  layerInteraction?: { selectedId: string; disabled: boolean; onSelect: (id: string) => void; onMove: (id: string, centerX: number, centerY: number) => void; onScale: (id: string, scale: number) => void }
}) {
  const host = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 600, height: 420 })
  const [compare, setCompare] = useState(false)
  const [split, setSplit] = useState(50)
  const [point, setPoint] = useState<{ x: number; y: number } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const checker = useImage(checkerboard(), attempt)
  const mask = useImage(selection?.overlayUrl, attempt)
  const painting = useRef<SelectionPoint[] | null>(null)
  const [paint, setPaint] = useState<SelectionPoint[]>([])
  const current = currentAsset(row, row.current_asset_id)
  const multi = row.document.layers.length > 1
  const beforeMulti = Boolean(row.previous_document && row.previous_document.layers.length > 1)
  const beforeId = row.previous_document?.layers.find(item => item.kind !== 'text')?.asset_id
  const before = beforeId ? currentAsset(row, beforeId) : undefined
  const image = useImage(layoutPreviewUrl ?? colorPreviewUrl ?? (multi ? compositeUrl(row.id, row.revision) : row.document.adjustments ? colorSourceUrl(row.id, row.revision) : current?.url), attempt)
  const beforeImage = useImage(beforeMulti ? compositeUrl(row.id, row.revision, true) : row.previous_document?.adjustments ? colorSourceUrl(row.id, row.revision, true) : before?.url, attempt)
  function retryImages() { setAttempt((value) => value + 1); onRefresh() }
  const { width, height } = row.document
  const key = `${userId}/${row.id}/${width}x${height}/${size.width}x${size.height}`
  const stored = useViewport((state) => state.views[key])
  const set = useViewport((state) => state.set)
  const fitScale = Math.min((size.width - 56) / width, (size.height - 56) / height, 1)
  const fit: Viewport = { scale: fitScale, x: (size.width - width * fitScale) / 2, y: (size.height - height * fitScale) / 2 }
  const view = stored ?? fit
  const comparing = compare && !selection?.active && !cropPreview && !colorPreviewUrl && !layoutOpen && Boolean(before && beforeImage?.image)
  const canSelectLayer = multi && !selection?.active && !cropPreview && !colorPreviewUrl && !layoutOpen && !layoutPreviewUrl && !comparing && !layerInteraction?.disabled && Boolean(layerInteraction)
  const previous = row.previous_document
  const previousScale = previous ? Math.min(width / previous.width, height / previous.height) : 1

  useEffect(() => {
    if (!host.current) return
    const observer = new ResizeObserver(([entry]) => {
      // Hidden navigation panels report zero dimensions. Keep the last useful viewport.
      if (entry.contentRect.width > 56 && entry.contentRect.height > 56) {
        setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
      }
    })
    observer.observe(host.current)
    return () => observer.disconnect()
  }, [])

  function zoom(scale: number, pointer = { x: size.width / 2, y: size.height / 2 }) {
    const next = Math.max(0.02, Math.min(8, scale))
    set(key, { scale: next, x: pointer.x - (pointer.x - view.x) / view.scale * next,
      y: pointer.y - (pointer.y - view.y) / view.scale * next })
  }

  function brushPoint(event: KonvaEventObject<PointerEvent>, clamp = false): SelectionPoint | null {
    const pointer = event.target.getStage()?.getPointerPosition()
    if (!pointer) return null
    const x = (pointer.x - view.x) / view.scale / width, y = (pointer.y - view.y) / view.scale / height
    if (!clamp && (x < 0 || x > 1 || y < 0 || y > 1)) return null
    return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))]
  }
  function beginStroke(event: KonvaEventObject<PointerEvent>) {
    if (!selection?.active || selection.disabled || event.evt.button !== 0) return
    const point = brushPoint(event)
    if (!point) return
    if (selection.tool === 'sam') { event.evt.preventDefault(); selection.onPoint?.(point); return }
    event.evt.preventDefault(); painting.current = [point]; setPaint([point])
    const target = event.evt.target
    if (target instanceof Element) target.setPointerCapture?.(event.evt.pointerId)
  }
  function moveStroke(event: KonvaEventObject<PointerEvent>) {
    if (!painting.current || !selection?.active) return
    const point = brushPoint(event, true)
    if (!point) return
    const last = painting.current[painting.current.length - 1]
    if (Math.hypot((point[0] - last[0]) * width, (point[1] - last[1]) * height) < Math.max(1, selection.radius / 4)) return
    if (painting.current.length < 1000) { painting.current.push(point); setPaint([...painting.current]) }
  }
  function endStroke() {
    const points = painting.current
    painting.current = null; setPaint([])
    if (points && selection?.active && !selection.disabled) selection.onStroke({ points, mode: selection.mode, radius: selection.radius / Math.min(width, height) })
  }
  const pending = selection?.pendingStroke
  const drawing = paint.length ? { points: paint, mode: selection?.mode, radius: (selection?.radius ?? 1) / Math.min(width, height) } : pending
  const line = drawing?.points.flatMap(([x, y]) => [x * width, y * height]) ?? []
  if (line.length === 2) line.push(line[0] + 0.01, line[1])

  return <div className="canvas-editor">
    <div className="canvas-toolbar" role="toolbar" aria-label="画布视口">
      <div className="zoom-controls">
        <button className="secondary icon-control" aria-label="缩小画布" onClick={() => zoom(view.scale / 1.2)}>−</button>
        <output aria-label="当前缩放">{Math.round(view.scale * 100)}%</output>
        <button className="secondary icon-control" aria-label="放大画布" onClick={() => zoom(view.scale * 1.2)}>＋</button>
      </div>
      <div className="view-controls">
        <button className="secondary" onClick={() => set(key, fit)}>适应窗口</button>
        <button className="secondary" onClick={() => zoom(1)}>原始比例</button>
      <button className={`secondary ${comparing ? 'tool-active' : ''}`} aria-pressed={comparing}
        disabled={!before || Boolean(cropPreview) || Boolean(colorPreviewUrl) || layoutOpen || selection?.active} onClick={() => setCompare(!compare)}>前后对比</button>
      </div>
      {toolbarExtra}
    </div>
    <div ref={host} className={`canvas-stage ${selection?.active ? 'is-brushing' : ''}`} data-testid="canvas-stage" data-view-scale={view.scale} data-view-x={view.x} data-view-y={view.y} data-layer-interaction={canSelectLayer ? 'ready' : 'disabled'} role="img" aria-label={`当前画布，${width}乘${height}像素；${selection?.active ? selection.tool === 'sam' ? '智能点选模式' : '笔刷选区模式' : canSelectLayer ? '点击图层边界选择，拖动可移动的图层，滚轮缩放' : '可拖动画面，滚轮缩放'}`}>
      {image?.image && checker?.image && <Stage width={size.width} height={size.height} x={view.x} y={view.y}
        scaleX={view.scale} scaleY={view.scale} draggable={!selection?.active}
        onPointerDown={beginStroke} onPointerMove={moveStroke} onPointerUp={endStroke}
        onPointerCancel={() => { painting.current = null; setPaint([]) }}
        onDragMove={(event) => { if (event.target === event.target.getStage()) set(key, { ...view, ...event.target.position() }) }}
        onWheel={(event) => { event.evt.preventDefault(); if (painting.current) return; const pointer = event.target.getStage()?.getPointerPosition();
          if (pointer) zoom(view.scale * (event.evt.deltaY > 0 ? 1 / 1.12 : 1.12), pointer) }}
        onMouseMove={(event) => { const pointer = event.target.getStage()?.getPointerPosition(); if (!pointer) return
          const x = (pointer.x - view.x) / view.scale, y = (pointer.y - view.y) / view.scale
          setPoint(x >= 0 && y >= 0 && x < width && y < height ? { x: Math.floor(x), y: Math.floor(y) } : null) }}
        onMouseLeave={() => setPoint(null)}>
        <Layer listening={false}>
          <DocumentPicture document={previewDocument(row.document, multi || Boolean(layoutPreviewUrl))} image={image.image} tile={checker.image} />
          {comparing && beforeImage?.image && previous && <Group clipX={0} clipY={0} clipWidth={width * split / 100} clipHeight={height}>
            <Rect width={width} height={height} fill="white" />
            <Group x={(width - previous.width * previousScale) / 2} y={(height - previous.height * previousScale) / 2} scaleX={previousScale} scaleY={previousScale}>
              <DocumentPicture document={previewDocument(previous, beforeMulti)} image={beforeImage.image} tile={checker.image} />
            </Group>
          </Group>}
          {cropPreview && <Group>
            <Rect width={width} height={cropPreview.y} fill="rgba(15,30,50,0.48)" />
            <Rect y={cropPreview.y + cropPreview.height} width={width} height={height - cropPreview.y - cropPreview.height} fill="rgba(15,30,50,0.48)" />
            <Rect y={cropPreview.y} width={cropPreview.x} height={cropPreview.height} fill="rgba(15,30,50,0.48)" />
            <Rect x={cropPreview.x + cropPreview.width} y={cropPreview.y} width={width - cropPreview.x - cropPreview.width} height={cropPreview.height} fill="rgba(15,30,50,0.48)" />
            <Rect {...cropPreview} stroke="white" strokeWidth={2 / view.scale} dash={[6 / view.scale, 4 / view.scale]} />
          </Group>}
          {comparing && <Line points={[width * split / 100, 0, width * split / 100, height]} stroke="white" strokeWidth={2 / view.scale} />}
        </Layer>
        {canSelectLayer && layerInteraction && <Layer>
          <Group clipX={0} clipY={0} clipWidth={width} clipHeight={height}>
            {row.document.layers.filter(item => item.visible).map(item => {
              const t = item.transform, selected = item.id === layerInteraction.selectedId
              const placement = layerValues(item)
              return <Group key={item.id} x={t.x} y={t.y} scaleX={t.scale_x} scaleY={t.scale_y} rotation={t.rotation}
                draggable={!item.locked} onClick={() => layerInteraction.onSelect(item.id)} onTap={() => layerInteraction.onSelect(item.id)}
                onDragStart={() => layerInteraction.onSelect(item.id)}
                onDragEnd={event => {
                  const deltaX = event.target.x() - t.x, deltaY = event.target.y() - t.y
                  event.target.position({ x: t.x, y: t.y })
                  if (Math.hypot(deltaX, deltaY) < 0.5) return
                  const centerX = +(placement.center_x + deltaX).toFixed(4), centerY = +(placement.center_y + deltaY).toFixed(4)
                  if (Math.abs(centerX) <= 100000 && Math.abs(centerY) <= 100000) layerInteraction.onMove(item.id, centerX, centerY)
                }}>
                <Rect width={item.width} height={item.height} fill="rgba(41,105,196,0.004)"
                  stroke={selected ? '#2674d3' : 'rgba(41,105,196,0.16)'} strokeWidth={selected ? 2 / view.scale : 1 / view.scale}
                  dash={selected ? [7 / view.scale, 4 / view.scale] : undefined} />
                {selected && !item.locked && <Circle x={item.width} y={item.height} radius={7 / view.scale / placement.scale}
                  fill="#ffffff" stroke="#2674d3" strokeWidth={2 / view.scale / placement.scale} draggable
                  onDragStart={event => { event.cancelBubble = true }}
                  onDragMove={event => { event.cancelBubble = true }}
                  onDragEnd={event => {
                    event.cancelBubble = true
                    const handle = event.target
                    const originalRadius = Math.hypot(item.width / 2, item.height / 2)
                    const radius = Math.hypot(handle.x() - item.width / 2, handle.y() - item.height / 2)
                    handle.position({ x: item.width, y: item.height })
                    const newScale = +(Math.max(0.05, Math.min(4, placement.scale * radius / originalRadius))).toFixed(4)
                    if (Math.abs(newScale - placement.scale) > 0.0001) layerInteraction.onScale(item.id, newScale)
                  }} />}
              </Group>
            })}
          </Group>
        </Layer>}
        {selection?.active && <Layer listening={false}><Group clipX={0} clipY={0} clipWidth={width} clipHeight={height}>
          {mask?.image && <CanvasImage image={mask.image} width={width} height={height}/>}
          {drawing && line.length >= 4 && <Line points={line} stroke="rgba(47,112,224,0.4)" strokeWidth={drawing.radius * Math.min(width, height) * 2} lineCap="round" lineJoin="round" globalCompositeOperation={drawing.mode === 'subtract' ? 'destination-out' : 'source-over'}/>}
          {selection.tool === 'sam' && selection.samPoints?.map((point, index) => <Group key={index} x={point.x * width} y={point.y * height}>
            <Circle radius={6 / view.scale} fill={point.label ? '#17816d' : '#ba4550'} stroke="white" strokeWidth={1.5 / view.scale}/>
            <Line points={[-3 / view.scale, 0, 3 / view.scale, 0]} stroke="white" strokeWidth={1.5 / view.scale}/>
            {point.label === 1 && <Line points={[0, -3 / view.scale, 0, 3 / view.scale]} stroke="white" strokeWidth={1.5 / view.scale}/>}
          </Group>)}
        </Group></Layer>}
      </Stage>}
      {(!image || !checker) && <p className="canvas-overlay" role="status">正在读取画布图片…</p>}
      {(image?.error || checker?.error) && <div className="canvas-overlay" role="alert"><p>图片预览加载失败，编辑记录仍已保存。</p><button className="secondary" onClick={retryImages}>重新读取图片</button></div>}
      {selection?.active && mask?.error && <div className="selection-mask-error" role="alert">选区显示未确认。<button className="text-button" onClick={retryImages}>重试显示选区</button></div>}
    </div>
    {compare && !selection?.active && before && !cropPreview && !colorPreviewUrl && !layoutOpen && <div className="compare-slider"><label htmlFor="canvas-compare">上一步</label>
      <input id="canvas-compare" type="range" min="0" max="100" value={split} aria-label="前后对比位置" onChange={(event) => setSplit(Number(event.target.value))} />
      <span>当前</span>{beforeImage?.error && <button className="text-button" onClick={retryImages}>对比图加载失败，重新读取</button>}</div>}
    <div className="canvas-status"><span>{width} × {height} px · {layoutPreviewUrl ? '变换预览未保存' : colorPreviewUrl ? '调色预览未保存' : '原图保留'}</span>
      <span>{point ? `图像坐标 ${point.x}, ${point.y}` : selection?.active ? selection.tool === 'sam' ? '点击识别物体 · 滚轮缩放 · Esc 完成' : '拖动涂抹选区 · 滚轮缩放 · Esc 完成' : canSelectLayer ? '点击边界选层 · 拖动图层 · 松开后预览并确认保存' : '拖动平移 · 滚轮缩放'}</span></div>
  </div>
}
