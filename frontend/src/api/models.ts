import { api } from './client'

export const modelsApi = {
  options: () => api.get<{
    planner_provider: 'dashscope' | 'zhipu'; planner_model: string
    planner_configured: boolean; vision_enabled: boolean; image_provider: string
    image_model: string; image_configured: boolean; image_max_count: number
    image_sizes: Record<string, [number, number]>
    reference_configured: boolean; reference_model: string; reference_max_count: number
    reference_max_images: number; reference_prompt_limit: number
    reference_min_side: number; reference_max_side: number; reference_max_bytes: number
  }>('/model-options'),
}
