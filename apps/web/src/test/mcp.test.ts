import { describe, expect, it } from 'vitest'
import { normalizeMcpConnections, safeMcpRedirect } from '../lib/mcp'

describe('server-returned OAuth redirects', () => {
  it('does not invent operator status or endpoints for legacy connection lists', () => {
    const connection = { id: 'synthetic', client_name: 'Synthetic', scopes: ['finance:read'], created_at: '2026-01-01' }
    expect(normalizeMcpConnections([connection, { ...connection, id: 'revoked', revoked: true }])).toEqual({ enabled: null, endpoint: null, scopes: [], connections: [connection] })
  })
  it.each(['https://chatgpt.com/callback?code=synthetic&state=synthetic', 'http://localhost:1234/callback', 'http://127.0.0.1:1234/callback', 'http://[::1]:1234/callback'])('accepts HTTPS or loopback: %s', value => {
    expect(safeMcpRedirect(value)).toBe(value)
  })
  it.each(['javascript:alert(1)', 'data:text/html,test', '//evil.invalid/callback', '/callback', 'http://evil.invalid/callback', 'https://synthetic-owner:synthetic-secret@example.invalid/callback', ' https://example.invalid', 'https://example.invalid\n', 'https:\\evil.invalid', null, {}])('rejects unsafe redirect: %s', value => {
    expect(safeMcpRedirect(value)).toBeNull()
  })
})
