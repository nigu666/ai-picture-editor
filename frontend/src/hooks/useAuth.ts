import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, type User } from '@/api/auth'
import { ApiError } from '@/api/client'

export const ME_KEY = ['auth', 'me']

export function useCurrentUser() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await authApi.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })
}

export function useAuthActions() {
  const client = useQueryClient()
  const cacheUser = async (user: User) => {
    await client.cancelQueries({ queryKey: ME_KEY })
    client.setQueryData(ME_KEY, user)
  }
  const login = useMutation({ mutationFn: authApi.login, onSuccess: cacheUser })
  const register = useMutation({ mutationFn: authApi.register, onSuccess: cacheUser })
  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: async () => {
      await client.cancelQueries()
      // 保留当前用户查询的订阅，显式通知路由守卫；清除其他用户业务缓存。
      client.setQueryData(ME_KEY, null)
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'auth' })
    },
  })
  return { login, register, logout }
}

export function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message
  return '暂时无法连接服务，请确认服务运行后重试'
}
