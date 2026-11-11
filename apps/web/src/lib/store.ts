import { create } from 'zustand'
import { getToken, setToken } from '@/api/client'

interface AuthState { token: string | null; set: (t: string | null) => void }
export const useAuth = create<AuthState>((set) => ({
  token: getToken(),
  set: (t) => { setToken(t); set({ token: t }) },
}))

interface Toast { id: number; kind: 'ok' | 'error'; text: string }
interface ToastState { toasts: Toast[]; push: (kind: Toast['kind'], text: string) => void; dismiss: (id: number) => void }
let n = 0
export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: (kind, text) => {
    const id = ++n
    set((s) => ({ toasts: [...s.toasts, { id, kind, text }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 5000)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

type Theme = 'light' | 'dark'
function initial(): Theme {
  try { const t = localStorage.getItem('cp.theme'); if (t === 'dark' || t === 'light') return t } catch { /* */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}
export const useTheme = create<{ theme: Theme; toggle: () => void }>((set, get) => ({
  theme: initial(),
  toggle: () => {
    const t = get().theme === 'dark' ? 'light' : 'dark'
    try { localStorage.setItem('cp.theme', t) } catch { /* */ }
    set({ theme: t })
  },
}))
