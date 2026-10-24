export default function AuthStatus({ onRetry }: { onRetry?: () => void }) {
  return (
    <main className="status-screen">
      <div className="status-box" role="status">
        <span className="brand-mark" aria-hidden="true">✦</span>
        <h1>{onRetry ? '暂时无法确认登录状态' : '正在确认登录状态'}</h1>
        <p>{onRetry ? '请稍后重试，确认成功后再继续。' : '稍等片刻，即将进入你的工作区。'}</p>
        {onRetry && <button className="primary" onClick={onRetry}>重新连接</button>}
      </div>
    </main>
  )
}
