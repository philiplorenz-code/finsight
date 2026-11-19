// Defense in depth only: OAuth redirect registration/validation belongs to the server.
// Never call this with a query-string/user-supplied return URL.
export function safeMcpRedirect(value: unknown): string | null {
  if (typeof value !== 'string' || value !== value.trim() || /[\u0000-\u0020\u007f\\]/.test(value)) return null
  try {
    const url = new URL(value)
    if (url.username || url.password) return null
    const loopback = url.hostname === 'localhost' || url.hostname === '[::1]' || /^127(?:\.\d{1,3}){3}$/.test(url.hostname)
    return url.protocol === 'https:' || (url.protocol === 'http:' && loopback) ? url.href : null
  } catch { return null }
}

export type McpAuthorization = {
  id: string
  client_id: string
  client_name: string
  redirect_uri: string
  scopes: string[]
  expires_at: string
  resource: string
}
export type McpConnections = {
  enabled: boolean | null
  endpoint: string | null
  scopes: string[]
  connections: { id: string; client_name: string; scopes: string[]; created_at: string; last_used_at?: string | null; revoked?: boolean }[]
}

export function normalizeMcpConnections(value: McpConnections | McpConnections['connections']): McpConnections {
  // Older API builds return only grants, without effective operator configuration.
  // Never infer enablement or a public resource URL from the browser's origin.
  return Array.isArray(value) ? { enabled: null, endpoint: null, scopes: [], connections: value.filter(connection => !connection.revoked) } : { ...value, connections: value.connections.filter(connection => !connection.revoked) }
}
