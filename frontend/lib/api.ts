// RoutePass — API client
// Thin fetch wrapper that:
//  1. Adds the JWT Authorization header from the auth store
//  2. Parses JSON responses and throws typed ApiError on non-2xx
//  3. Re-exports all response types for convenient import
//
// Usage:
//   import { apiGet, apiPost } from '@/lib/api'
//   const activities = await apiGet<PaginatedActivities>('/api/v1/activities')

import type { ApiError } from '@/types/api'

const BASE = ''  // rewrites in next.config.ts proxy /api/* → FastAPI

// ── Auth token accessor (lazy import to avoid circular deps) ──────────────────

let _getToken: (() => string | null) | null = null
let _onUnauthorized: (() => void) | null = null

export function registerTokenAccessor(fn: () => string | null) {
  _getToken = fn
}

/** Called whenever the API returns 401. Use to redirect to /login. */
export function registerUnauthorizedHandler(fn: () => void) {
  _onUnauthorized = fn
}

function authHeader(): Record<string, string> {
  const token = _getToken?.()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// ── Core fetch helper ─────────────────────────────────────────────────────────

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...authHeader(),
    ...extraHeaders,
  }

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'include',
  })

  if (!res.ok) {
    if (res.status === 401) {
      _onUnauthorized?.()
    }
    let detail = `HTTP ${res.status}`
    try {
      const err = (await res.json()) as ApiError
      detail = err.detail ?? detail
    } catch {
      // response body wasn't JSON — use the status text
      detail = res.statusText || detail
    }
    throw new ApiRequestError(detail, res.status)
  }

  // 204 No Content
  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

// Typed error for consumers to catch specifically
export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
    this.name = 'ApiRequestError'
  }

  get isUnauthorized()  { return this.status === 401 }
  get isPaymentRequired() { return this.status === 402 }
  get isForbidden()     { return this.status === 403 }
  get isNotFound()      { return this.status === 404 }
}

// ── Public helpers ────────────────────────────────────────────────────────────

export const apiGet = <T>(path: string) =>
  request<T>('GET', path)

export const apiPost = <T>(path: string, body?: unknown) =>
  request<T>('POST', path, body)

export const apiPut = <T>(path: string, body?: unknown) =>
  request<T>('PUT', path, body)

export const apiPatch = <T>(path: string, body?: unknown) =>
  request<T>('PATCH', path, body)

export const apiDelete = <T = void>(path: string) =>
  request<T>('DELETE', path)

// Multipart form POST (for file uploads — e.g. Runalyze GPX)
export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: authHeader(),
    body: form,
    credentials: 'include',
  })
  if (!res.ok) {
    const err = (await res.json().catch(() => ({ detail: res.statusText }))) as ApiError
    throw new ApiRequestError(err.detail, res.status)
  }
  return res.json() as Promise<T>
}
