import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import RequireAuth from '@/layouts/RequireAuth'
import AuthPage from '@/pages/AuthPage'
import EditorPage from '@/pages/EditorPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/editor" element={<EditorPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/editor" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
