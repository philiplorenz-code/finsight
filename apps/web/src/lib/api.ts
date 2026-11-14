export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = 'ApiError' }
}

let csrfToken = ''
export function setCsrf(token?: string) { csrfToken = token || '' }
function cookieToken() {
  const cookie = document.cookie.split('; ').find(c => /^(csrf_token|csrf|finsight_csrf)=/.test(c))
  return cookie ? decodeURIComponent(cookie.substring(cookie.indexOf('=') + 1)) : ''
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Only same-origin API paths are allowed')
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const token = cookieToken() || csrfToken
  if (!['GET', 'HEAD', 'OPTIONS'].includes((init.method || 'GET').toUpperCase()) && token) headers.set('X-CSRF-Token', token)
  const response = await fetch(`/api${path}`, { ...init, headers, credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) {
    // Never render server exception details, request bodies or credentials.
    throw new ApiError(response.status, response.status === 429 ? 'rate_limit' : response.status === 401 ? 'unauthorized' : response.status === 403 ? 'forbidden' : response.status === 409 && path.startsWith('/ai/') ? 'ai_blocked' : response.status === 409 ? 'conflict' : response.status === 422 || response.status === 400 ? 'invalid' : 'unavailable')
  }
  if (response.status === 204) return undefined as T
  const data = await response.json()
  if (data && typeof data.csrf_token === 'string') setCsrf(data.csrf_token)
  return data as T
}
export const send = <T = unknown>(path: string, body?: unknown, method = 'POST') => api<T>(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
export function items<T>(data: T[] | { items?: T[]; results?: T[] } | undefined): T[] {
  if (Array.isArray(data)) return data
  return data?.items || data?.results || []
}
export function queryString(values: Record<string, string | number | boolean | undefined>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)) })
  return params.size ? `?${params}` : ''
}
