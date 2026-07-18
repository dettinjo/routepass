// RoutePass — Auth store (Zustand)
// Stores the JWT in memory (never localStorage/sessionStorage — XSS risk).
// The token is also sent as a JS-readable cookie so AuthInitializer can
// restore the session on every page refresh.
//
// Consumers:
//   const { token, user, initialized, login, logout } = useAuthStore()
//
// Session restoration flow:
//   1. Page loads: token=null, initialized=false
//   2. AuthInitializer reads rp_token cookie, calls /api/v1/auth/me
//   3a. Success → login() → initialized=true, token set
//   3b. Failure / no cookie → setInitialized() → initialized=true, token stays null
//   4. Unauthorized handler only fires redirect when initialized=true
//   5. AuthGuard only redirects when initialized=true and token=null

import { create } from 'zustand'
import type { UserMe } from '@/types/api'
import { registerTokenAccessor, registerUnauthorizedHandler } from '@/lib/api'

interface AuthState {
  token: string | null
  user: UserMe | null
  /** True once the initial session-restore attempt has completed. */
  initialized: boolean
  login: (token: string, user: UserMe) => void
  logout: () => void
  setUser: (user: UserMe) => void
  /** Called by AuthInitializer when restore attempt ends (success or fail). */
  setInitialized: () => void
}

// Keep the browser session alive for 30 days. AuthInitializer re-writes the
// cookie (and rolls the JWT via /auth/refresh) on every visit, so an active
// user's window slides forward and never expires — Instagram-style persistence.
const SESSION_MAX_AGE = 60 * 60 * 24 * 30 // 30 days, in seconds

function writeTokenCookie(token: string): void {
  const secure = typeof window !== 'undefined' && window.location.protocol === 'https:'
  document.cookie =
    `rp_token=${token}; path=/; SameSite=Lax; max-age=${SESSION_MAX_AGE}` +
    (secure ? '; Secure' : '')
}

function clearTokenCookie(): void {
  document.cookie = 'rp_token=; path=/; SameSite=Lax; max-age=0'
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  initialized: false,

  login(token, user) {
    set({ token, user, initialized: true })
    writeTokenCookie(token)
  },

  logout() {
    set({ token: null, user: null, initialized: true })
    clearTokenCookie()
  },

  setUser(user) {
    set({ user })
  },

  setInitialized() {
    set({ initialized: true })
  },
}))

// Wire the auth store into the API client so apiGet/apiPost auto-attach the JWT
registerTokenAccessor(() => useAuthStore.getState().token)

// On any 401 response: redirect to /login — but ONLY after initialization is
// complete. 401s that arrive while we are still restoring the session from
// cookie are normal (the token hasn't been re-injected into the request yet)
// and must not trigger a redirect.
registerUnauthorizedHandler(() => {
  const { initialized, logout } = useAuthStore.getState()
  if (!initialized) return
  logout()
  if (typeof window !== 'undefined') {
    window.location.replace('/login')
  }
})
