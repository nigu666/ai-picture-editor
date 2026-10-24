import { create } from 'zustand'

export type Viewport = { x: number; y: number; scale: number }
type ViewportStore = {
  views: Record<string, Viewport>
  set: (key: string, value: Viewport) => void
}

// 视口仅在前端内存保存；刷新重新适配，不写入会话或编辑历史。
export const useViewport = create<ViewportStore>((set) => ({
  views: {},
  set: (key, value) => set((state) => ({ views: { ...state.views, [key]: value } })),
}))
