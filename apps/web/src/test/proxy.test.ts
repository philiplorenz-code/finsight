import { describe, expect, it } from 'vitest'
import config from '../../nginx.conf?raw'
import dockerfile from '../../Dockerfile?raw'

describe('shipped proxy safety contract (not a deployed smoke test)', () => {
  it('preserves public non-default ports for same-origin auth validation', () => {
    expect(config).toContain('proxy_set_header Host $http_host;')
    expect(config).not.toMatch(/proxy_set_header\s+Host\s+\$host;/)
    expect(config).toContain('proxy_pass http://finsight_api;')
  })
  it('re-resolves the API after replacement without capturing the SPA consent route', () => {
    expect(config).toContain('server ${FINSIGHT_API_UPSTREAM} resolve;')
    expect(config).toContain('resolver ${FINSIGHT_NGINX_RESOLVER} valid=5s ipv6=off;')
    // Docker compose defaults are baked into the image; Kubernetes overrides them.
    expect(dockerfile).toContain('FINSIGHT_API_UPSTREAM=api:8000 FINSIGHT_NGINX_RESOLVER=127.0.0.11 NGINX_ENVSUBST_FILTER=^FINSIGHT_')
    expect(config).toContain('location = /mcp {')
    expect(config).toContain('location = /mcp/ {')
    expect(config).not.toContain('location /mcp {')
    expect(config).toContain('add_header Referrer-Policy no-referrer always;')
  })
  it('disables access logs before any location, including SPA routes and assets', () => {
    expect(config.slice(0, config.indexOf('location '))).toContain('access_log off;')
    expect(config).not.toMatch(/access_log\s+(?!off;)[^;]+;/)
  })
  it('does not forward an untrusted client scheme or authority override', () => {
    expect(config).toContain('proxy_set_header X-Forwarded-Proto $scheme;')
    expect(config).not.toContain('$http_x_forwarded_proto')
    expect(config).not.toContain('$http_x_forwarded_host')
  })
})
