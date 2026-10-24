import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { modelsApi } from '@/api/models'
import { generationHistoryKey, runKey, runsApi, type GenerateInput, type GenerationRecord } from '@/api/runs'
import GenerationHistory from './GenerationHistory'
import GenerationReferences from './GenerationReferences'
import type { Asset } from '@/api/assets'
import type { User } from '@/api/auth'
import { errorMessage, ME_KEY } from '@/hooks/useAuth'
import { useRun } from '@/hooks/useRun'

const labels = { queued: '等待执行', running: '正在生成', succeeded: '生成完成', failed: '生成失败' }

function Candidate({ asset, index, selected, onChoose, onEdit, editingBusy }: {
  asset: Asset; index: number; selected: boolean; onChoose: () => void; onEdit: () => void; editingBusy: boolean
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  return <article className={`candidate-card ${selected ? 'is-selected' : ''}`}>
    <div className="candidate-preview">
      {failedUrl === asset.url ? <p>预览暂不可用，请点击“重新读取状态”更新图片地址。</p>
        : <img src={asset.url} alt={`生成候选 ${index + 1}`} onError={() => setFailedUrl(asset.url)} />}
      <span className="candidate-number">候选 {index + 1}</span>
    </div>
    <div className="candidate-info"><p>{asset.width} × {asset.height} · {asset.image_format}</p>
      <button className={selected ? 'primary' : 'secondary'} aria-pressed={selected} onClick={onChoose}>
        {selected ? '已选为当前候选' : `选择候选 ${index + 1}`}
      </button>
      <button className="secondary" disabled={editingBusy} onClick={onEdit}>以候选 {index + 1} 新建编辑会话</button>
      <a href={asset.url} target="_blank" rel="noopener noreferrer">查看原图 ↗</a>
    </div>
  </article>
}

export default function GeneratePanel({ userId, onEdit, onAdd, editingBusy }: {
  userId: string; onEdit: (asset: Asset, ids: string[]) => void; onAdd?: (ids: string[]) => void; editingBusy: boolean
}) {
  const client = useQueryClient()
  const [search, setSearch] = useSearchParams()
  const runId = search.get('run')
  const task = useRun(userId, runId)
  const [prompt, setPrompt] = useState('')
  const [ratio, setRatio] = useState<GenerateInput['ratio']>('1:1')
  const [count, setCount] = useState(1)
  const [seed, setSeed] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [reuseNotice, setReuseNotice] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [referenceIds, setReferenceIds] = useState<string[]>([])
  const [referenceValid, setReferenceValid] = useState(false)
  const withReferences = referenceIds.length > 0
  const models = useQuery({ queryKey: ['model-options', userId], queryFn: async () => {
    try { return await modelsApi.options() } catch (error) {
      if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
      throw error
    }
  } })
  const real = models.data?.image_provider === 'dashscope'
  const maxCount = withReferences ? models.data?.reference_max_count ?? 1 : models.data?.image_max_count ?? 1
  const promptLimit = withReferences ? models.data?.reference_prompt_limit ?? 800 : 1500
  const promptValid = Boolean(prompt.trim()) && prompt.length <= promptLimit
  const configured = models.data?.image_configured && (!withReferences || (models.data.reference_configured && referenceValid))
  const chosenCount = Math.min(count, maxCount)
  const outputSize = models.data?.image_sizes[ratio]
  const [selected, setSelected] = useState<{ run: string; asset: string } | null>(null)
  const submitting = useRef(false)
  const submission = useMutation({ mutationFn: runsApi.generate, retry: false })
  const busy = submission.isPending || Boolean(runId && !task.terminal && !task.inaccessible)
  const uncertainResolved = submission.error instanceof ApiError && submission.error.runId === runId && task.terminal
  const seedValid = !seed.trim() || (/^\d+$/.test(seed) && Number.isSafeInteger(Number(seed)) && Number(seed) <= 2147483647)
  const negativeValid = negativePrompt.trim().length <= 500 && (real || !negativePrompt.trim())

  useEffect(() => {
    if (runId && task.terminal) void client.invalidateQueries({ queryKey: generationHistoryKey(userId) })
  }, [client, runId, task.terminal, userId])

  function reuse(record: GenerationRecord) {
    if (busy) return
    setPrompt(record.prompt)
    if (record.ratio) setRatio(record.ratio)
    const references = record.reference_asset_ids ?? []
    const limit = references.length ? models.data?.reference_max_count ?? 1 : models.data?.image_max_count ?? 1
    setReferenceIds(references)
    setCount(Math.min(record.count, limit))
    setSeed(record.seed === null ? '' : String(record.seed))
    setNegativePrompt(record.negative_prompt ?? '')
    setAdvancedOpen(record.seed !== null || Boolean(record.negative_prompt))
    setReuseNotice(`已填入记录参数，尚未提交。生成时使用当前模式的模型与尺寸。${references.length ? '已恢复参考图选择，正在核对素材。' : ''}${record.count > limit ? `张数已按当前上限调整为${limit}张。` : ''}${!record.ratio ? '原比例不在当前选项中，保留表单比例。' : ''}`)
    submission.reset()
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (submitting.current || busy || !promptValid || !configured || !seedValid || !negativeValid) return
    submitting.current = true
    setReuseNotice('')
    submission.mutate({ prompt: prompt.trim(), ratio, count: chosenCount,
      ...(seed.trim() ? { seed: Number(seed) } : {}),
      ...(negativePrompt.trim() ? { negative_prompt: negativePrompt.trim() } : {}),
      ...(withReferences ? { reference_asset_ids: referenceIds } : {}),
    }, {
      onSuccess: (run) => {
        client.setQueryData(runKey(userId, run.id), run)
        setSearch((previous) => { previous.set('run', run.id); return previous })
      },
      onError: (error) => {
        if (error instanceof ApiError && error.status === 401 && client.getQueryData<User>(ME_KEY)?.id === userId) client.setQueryData(ME_KEY, null)
        if (error instanceof ApiError && error.runId) setSearch((previous) => { previous.set('run', error.runId!); return previous })
      },
      onSettled: () => {
        submitting.current = false
        void client.invalidateQueries({ queryKey: generationHistoryKey(userId) })
      },
    })
  }

  return <section className="generation-section" aria-labelledby="generation-heading">
    <div className="generation-heading"><div><p className="eyebrow">从描述到候选图</p><h2 id="generation-heading">生成图片</h2></div>
      <span className="mode-pill">{!models.data ? '正在读取配置' : !models.data.image_configured || (withReferences && !models.data.reference_configured) ? '生图待配置' : withReferences ? '百炼 · 参考图生成' : real ? '百炼 · 真实生成' : 'Mock 学习演示'}</span></div>
    <p className="generation-note">{!models.data ? '正在读取当前生图模式…' : real
      ? withReferences ? `使用 ${models.data.reference_model}，本次参考${referenceIds.length}张原图生成1张候选，按张计费。原图保留，检查后再采用。` : `使用 ${models.data.image_model}，按张计费。结果先进入候选，由你决定是否采用；未选参考图时仅使用文字。`
      : '生成带标记的占位图，用于体验完整流程；不表达描述中的真实画面效果。'}</p>
    {(models.isError || (models.data && !models.data.image_configured)) && <p className="error-message" role="alert">
      {models.isError ? '生图配置读取失败。' : '生图配置尚未就绪，请检查本机密钥和接口设置后重启后端。'}
      <button className="text-button" type="button" onClick={() => { void models.refetch() }} disabled={models.isFetching}>重新读取配置</button></p>}
    <div className="generation-workbench">
      <form className="generation-form" onSubmit={submit}>
        <label htmlFor="generation-prompt">描述你想要的画面</label>
        <textarea id="generation-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)}
          placeholder={withReferences ? '例如：将图1中的杯子改为深蓝色，保留橙子、桌面和窗光' : '例如：傍晚窗边的一束花，柔和自然光'} required maxLength={promptLimit} rows={5} disabled={busy} />
        <p className="generation-help">{prompt.length} / {promptLimit}{outputSize ? ` · ${outputSize[0]} × ${outputSize[1]}` : ''}{real && !withReferences ? ' · 不自动参考当前画布' : ''}</p>
        {prompt.length > promptLimit && <p className="error-message" role="alert">原描述超过当前{promptLimit}字上限，请先修改；不会自动截断。</p>}
        <GenerationReferences userId={userId} selected={referenceIds} onValidityChange={setReferenceValid}
          onChange={(ids) => { setReferenceIds(ids); if (ids.length > 0) setCount(1) }}
          enabled={Boolean(models.data?.reference_configured)} disabled={busy}
          maxImages={models.data?.reference_max_images ?? 3} minSide={models.data?.reference_min_side ?? 384}
          maxSide={models.data?.reference_max_side ?? 3072} maxBytes={models.data?.reference_max_bytes ?? 10485760} />
        <div className="generation-options"><div><label htmlFor="generation-ratio">画面比例</label>
          <select id="generation-ratio" value={ratio} onChange={(event) => setRatio(event.target.value as GenerateInput['ratio'])} disabled={busy}>
            <option value="1:1">1:1 · 方形</option><option value="4:5">4:5 · 竖幅</option><option value="3:4">3:4 · 竖幅</option>
            <option value="9:16">9:16 · 长竖幅</option><option value="16:9">16:9 · 横幅</option>
          </select></div><div><label htmlFor="generation-count">候选数量</label>
          <select id="generation-count" value={chosenCount} onChange={(event) => setCount(Number(event.target.value))} disabled={busy || !models.data?.image_configured}>
            {Array.from({ length: maxCount }, (_, index) => index + 1).map((number) => <option key={number} value={number}>{number} 张</option>)}
          </select></div></div>
        <details className="generation-advanced" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
          <summary>更多生成参数{seed || negativePrompt ? ' · 已填写' : '（可选）'}</summary>
          <label htmlFor="generation-negative">不希望出现的内容</label>
          <textarea id="generation-negative" value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)}
            rows={2} maxLength={500} disabled={busy} placeholder="例如：画面模糊、多余物体" />
          <p className="generation-help">{negativePrompt.length} / 500 · {real ? '反向描述用于限制画面内容' : 'Mock模式不支持反向描述，请留空'}</p>
          <label htmlFor="generation-seed">随机种子</label>
          <input id="generation-seed" type="number" min={0} max={2147483647} step={1} value={seed}
            onChange={(event) => setSeed(event.target.value)} disabled={busy} placeholder="留空使用随机值" />
          <p className="generation-help">0～2147483647；同一种子不保证图片完全一致。</p>
        </details>
        {!seedValid && <p className="error-message" role="alert">种子须为0～2147483647的整数。</p>}
        {!negativeValid && <p className="error-message" role="alert">{!real && negativePrompt.trim() ? '当前Mock模式不支持反向描述，请清空该字段。' : '原记录的反向描述超过当前500字上限，请先调整。'}</p>}
        {reuseNotice && <p className="connection-notice" role="status">{reuseNotice}</p>}
        <button className="primary generate-submit" type="submit" disabled={busy || !promptValid || !configured || !seedValid || !negativeValid}>
          {submission.isPending ? '正在提交…' : busy ? '任务处理中…' : '生成候选图'}</button>
        {runId && task.terminal && <p className="generation-help">当前结果保留原任务的尺寸；表单设置用于下一次生成。</p>}
        {submission.isError && !uncertainResolved && <p className="error-message" role="alert">{errorMessage(submission.error)}
          {!(submission.error instanceof ApiError) && '；未能确认提交结果，再次提交可能产生重复任务。'}</p>}
      </form>
      <div className="generation-result">
        {!runId ? <div className="generation-empty"><span aria-hidden="true">＋</span><h3>在这里比较你的候选图</h3><p>填写描述并提交，进度和结果会显示在这里。</p></div>
          : <><div className="run-heading"><h3>{task.inaccessible ? '无法查看任务' : task.display ? labels[task.display.status] : '正在核对任务'}</h3>
            <button className="text-button" onClick={() => { void task.snapshot.refetch() }} disabled={task.snapshot.isFetching}>重新读取状态</button></div>
            <p className="run-id">任务编号 <span>{runId}</span></p>
            {task.display && <div className="run-progress"><label htmlFor="generation-progress">{task.display.stage} <strong>{task.display.progress}%</strong></label>
              <progress id="generation-progress" value={task.display.progress} max={100} />
              <p>执行来源：{task.display.provider === 'mock' ? 'Mock 占位图' : task.display.result.generation_mode === 'reference' ? '百炼参考图编辑' : task.display.provider === 'dashscope' ? '百炼真实文生图' : task.display.provider}{task.display.result.model && task.display.provider !== 'mock' ? ` · ${task.display.result.model}` : ''}</p></div>}
            {task.reconnecting && <p className="connection-notice" role="status">进度连接暂时中断，正在重新核对；任务可能仍在执行。</p>}
            {task.snapshot.isError && <p className="error-message" role="alert">{task.inaccessible ? '无法查看该任务，请确认任务编号和当前账号。' : errorMessage(task.snapshot.error)}</p>}
            {task.display?.error && <p className="error-message" role="alert">{task.display.error}</p>}
            {task.display?.status === 'succeeded' && task.snapshot.isFetching && <p role="status">正在读取已保存的候选图…</p>}
            <div className="candidate-grid">{task.candidates.map((asset, index) => <Candidate key={asset.id} asset={asset} index={index}
              selected={selected?.run === runId && selected.asset === asset.id} onChoose={() => setSelected({ run: runId, asset: asset.id })}
              onEdit={() => onEdit(asset, task.candidates.map((item) => item.id))} editingBusy={editingBusy} />)}</div>
            {onAdd && task.candidates.length > 0 && <button className="secondary add-to-session" disabled={editingBusy}
              onClick={() => onAdd(task.candidates.map((item) => item.id))}>将本组候选加入当前会话</button>}
            {selected?.run === runId && <p className="chosen-notice" role="status">已选中供比较。新建编辑会话或加入当前会话后，可在工作台明确采用。</p>}
            {task.display?.status === 'failed' && task.candidates.length > 0 && <p className="connection-notice">本次任务失败，已保存的部分候选仍可查看。</p>}
          </>}
      </div>
    </div>
    <GenerationHistory key={userId} userId={userId} currentId={runId}
      openingDisabled={submission.isPending} reuseDisabled={busy || !models.data?.image_configured}
      onOpen={(id) => {
        submission.reset()
        setSearch((previous) => { previous.set('run', id); return previous })
      }} onReuse={reuse} />
  </section>
}
