import { api } from './client'

export type User = { id: string; username: string }
export type Credentials = { username: string; password: string }

export const authApi = {
  me: () => api.get<User>('/auth/me'),
  register: (credentials: Credentials) => api.post<User>('/auth/register', credentials),
  login: (credentials: Credentials) => api.post<User>('/auth/login', credentials),
  logout: () => api.post<void>('/auth/logout'),
}
