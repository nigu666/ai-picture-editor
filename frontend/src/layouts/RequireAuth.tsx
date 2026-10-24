import { Navigate, Outlet } from 'react-router-dom'
import AuthStatus from '@/components/AuthStatus'
import { useCurrentUser } from '@/hooks/useAuth'

export default function RequireAuth() {
  const current = useCurrentUser()
  if (current.isPending) return <AuthStatus />
  if (current.isError) return <AuthStatus onRetry={() => { void current.refetch() }} />
  return current.data ? <Outlet /> : <Navigate to="/auth" replace />
}
