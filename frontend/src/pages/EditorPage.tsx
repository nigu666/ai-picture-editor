import { useAuthActions, useCurrentUser, errorMessage } from '@/hooks/useAuth'
import AssetLibrary from '@/components/AssetLibrary'
import GeneratePanel from '@/components/GeneratePanel'
import SessionWorkbench from '@/components/SessionWorkbench'
import { useEditorSession } from '@/hooks/useEditorSession'
import AgentPanel from '@/components/AgentPanel'
import { useSearchParams } from 'react-router-dom'

type View = 'editor' | 'generate' | 'assets'

function EditorContent({ userId, view, onView }: { userId: string; view: View; onView: (value: View) => void }) {
  const editor = useEditorSession(userId)
  return <>
    <div hidden={view !== 'editor'} id="view-editor">
      <SessionWorkbench editor={editor} userId={userId} onStart={onView}
        assistant={editor.detail.data && !editor.detail.isError && <AgentPanel key={editor.detail.data.id} userId={userId} session={editor.detail.data} editingBusy={editor.mutation.isPending} />} />
    </div>
    <div hidden={view !== 'generate'} id="view-generate">
    <GeneratePanel userId={userId} onEdit={(asset, ids) => { onView('editor'); editor.create(asset, ids) }}
      onAdd={editor.id && editor.detail.data && !editor.detail.isError ? (ids) => editor.change({ action: 'assets', body: { asset_ids: ids } }) : undefined}
      editingBusy={editor.mutation.isPending} />
    </div>
    <div hidden={view !== 'assets'} id="view-assets">
    <AssetLibrary userId={userId} onEdit={(asset) => { onView('editor'); editor.create(asset) }} editingBusy={editor.mutation.isPending}
      sessionAssetIds={editor.detail.data?.assets.map(asset => asset.id)}
      onAdd={editor.id && editor.detail.data && !editor.detail.isError ? asset => editor.change({ action: 'assets', body: { asset_ids: [asset.id] } }) : undefined} />
    </div>
  </>
}

export default function EditorPage() {
  const current = useCurrentUser()
  const { logout } = useAuthActions()
  const [search, setSearch] = useSearchParams()
  const requestedView = search.get('view')
  const view: View = requestedView === 'generate' || requestedView === 'assets' ? requestedView
    : requestedView === 'editor' ? 'editor' : search.has('run') && !search.has('session') ? 'generate' : 'editor'
  function setView(value: View) {
    setSearch(previous => { previous.set('view', value); return previous }, { replace: true })
  }
  return (
    <div className="workspace floating-workspace">
      <header className="workspace-header">
        <div className="wordmark"><span className="workbench-logo" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="4"/><path d="m7 16 4-5 3 3 3-4M16 7h.01"/></svg></span> 修图智能体</div>
        <nav className="workspace-navigation" data-view={view} aria-label="创作空间">{([{ id: 'editor', label: '工作台' }, { id: 'generate', label: '生成图片' }, { id: 'assets', label: '素材库' }] as const).map(item =>
          <button key={item.id} type="button" aria-pressed={view === item.id} aria-controls={`view-${item.id}`} onClick={() => setView(item.id)}>{item.label}</button>)}</nav>
        <div className="account"><span title={current.data?.username}>你好，<strong>{current.data?.username}</strong></span>
          <button className="secondary" onClick={() => logout.mutate()} disabled={logout.isPending}>
            {logout.isPending ? '正在退出…' : '退出登录'}
          </button>
        </div>
      </header>
      {logout.isError && <p className="error-message workspace-error" role="alert">{errorMessage(logout.error)}</p>}
      <main className="workspace-main">
        <h1 className="sr-only">图片创作工作区</h1>
        {current.data && <EditorContent key={current.data.id} userId={current.data.id} view={view} onView={setView} />}
      </main>
    </div>
  )
}
