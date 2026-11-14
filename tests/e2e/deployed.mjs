/** Real browser + shipped proxy + live API. Isolated synthetic installation only. */
import assert from 'node:assert/strict'
import { createHash, randomBytes } from 'node:crypto'
import { mkdirSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

if (process.env.FINSIGHT_SYNTHETIC_SMOKE !== '1') throw new Error('Requires explicit FINSIGHT_SYNTHETIC_SMOKE=1 on a disposable synthetic installation')
const base = process.env.FINSIGHT_SMOKE_BASE_URL || 'http://localhost:8080'
assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname), 'Only local isolated deployments are accepted')
const config = Object.fromEntries(readFileSync(new URL('../../.env', import.meta.url), 'utf8').split('\n').filter(line => line && !line.startsWith('#') && line.includes('=')).map(line => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)]))
const bootstrap = config.FINSIGHT_BOOTSTRAP_SECRET
assert.ok(bootstrap)
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, locale: 'de-DE', reducedMotion: 'reduce' })
  const pageErrors = []
  page.on('pageerror', () => pageErrors.push('redacted browser error'))
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    return url.origin === new URL(base).origin ? route.continue() : route.abort()
  })
  await page.goto(base)
  await page.locator('input[type="email"]').fill('smoke@example.invalid')
  await page.locator('input[type="password"]').fill(createHash('sha256').update(bootstrap + 'synthetic-smoke').digest('hex'))
  await page.locator('form button[type="submit"]').click()
  await page.getByRole('button', { name: 'Eigener Zeitraum', exact: true }).waitFor()
  const meResponse = await page.request.get(base + '/api/auth/me')
  assert.equal(meResponse.status(), 200, 'Real browser session cookie must work behind the shipped proxy')
  const me = await meResponse.json()
  assert.ok(me.email === 'smoke@example.invalid', 'Refusing a non-synthetic owner')
  const transactions = await (await page.request.get(base + '/api/transactions')).json()
  assert.ok(transactions.total === 4, 'Refusing to capture an installation with extra data')
  assert.ok(transactions.items.every(item => item.merchant === 'Synthetic provider'), 'Synthetic-only capture guard')
  const accounts = await (await page.request.get(base + '/api/accounts')).json()
  assert.ok(JSON.stringify(accounts.map(account => account.name).sort()) === JSON.stringify(['TEST-CHECKING', 'TEST-SAVINGS']), 'Synthetic account-name guard failed')
  const denied = await page.request.patch(base + '/api/accounts/' + accounts[0].id, { data: { name: 'TEST-DENIED' } })
  assert.equal(denied.status(), 403, 'Cookie alone must not authorize a mutation')

  await page.getByRole('button', { name: 'Eigener Zeitraum', exact: true }).click()
  await page.getByLabel('Von', { exact: true }).fill('2025-10-01')
  const loaded = page.waitForResponse(response => response.url().includes('/api/overview?') && response.url().includes('end=2025-10-31') && response.status() === 200)
  await page.getByLabel('Bis', { exact: true }).fill('2025-10-31')
  await loaded
  await page.locator('.stat-card').first().getByText(/2\.000/).waitFor()
  assert.equal(pageErrors.length, 0)
  if (process.env.FINSIGHT_CAPTURE_SCREENSHOTS === '1') {
    const destination = new URL('../../docs/screenshots/', import.meta.url)
    mkdirSync(destination, { recursive: true })
    await page.screenshot({ path: new URL('dashboard.png', destination).pathname, fullPage: true, animations: 'disabled' })
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => document.documentElement.scrollWidth <= window.innerWidth, null, { timeout: 5000 })
  if (process.env.FINSIGHT_CAPTURE_SCREENSHOTS === '1') {
    await page.screenshot({ path: new URL('../../docs/screenshots/mobile.png', import.meta.url).pathname, fullPage: true, animations: 'disabled' })
  }
  const expectMcp = process.env.FINSIGHT_EXPECT_MCP_ENABLED === '1'
  const connections = await (await page.request.get(base + '/api/mcp/connections')).json()
  assert.equal(connections.enabled, expectMcp)
  await page.goto(base + '/settings/mcp')
  await page.getByText(expectMcp ? 'Server aktiviert' : 'Server deaktiviert', { exact: true }).waitFor()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  if (expectMcp) {
    const callback = base + '/synthetic-mcp-callback'
    // Emulate only the local test client's callback, not any FinSight API route.
    await page.route(callback + '*', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Synthetic OAuth callback</title>' }))
    const client = await (await page.request.post(base + '/oauth/register', { data: {
      client_name: 'Synthetic browser client', redirect_uris: [callback], token_endpoint_auth_method: 'none',
      scope: 'finance:read finance:transactions',
    } })).json()
    const verifier = randomBytes(48).toString('base64url')
    const challenge = createHash('sha256').update(verifier).digest('base64url')
    const state = randomBytes(24).toString('base64url')
    const params = new URLSearchParams({ response_type: 'code', client_id: client.client_id, redirect_uri: callback,
      scope: 'finance:read finance:transactions', resource: base + '/mcp', state,
      code_challenge: challenge, code_challenge_method: 'S256' })
    await page.goto(base + '/oauth/authorize?' + params)
    await page.getByRole('heading', { name: 'Synthetic browser client', exact: true }).waitFor()
    await page.getByText(callback, { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Zugriff ausdrücklich erlauben', exact: true }).isDisabled(), true)
    const checks = page.locator('.mcp-consent input[type="checkbox"]')
    assert.equal(await checks.first().isChecked(), false, 'Transaction details remain opt-in')
    await checks.last().check()
    await page.getByRole('button', { name: 'Zugriff ausdrücklich erlauben', exact: true }).click()
    await page.waitForURL(url => url.pathname === '/synthetic-mcp-callback' && url.searchParams.has('code'))
    const returned = new URL(page.url())
    assert.equal(returned.searchParams.get('state'), state)
    const response = await page.request.post(base + '/oauth/token', { form: {
      grant_type: 'authorization_code', client_id: client.client_id, code: returned.searchParams.get('code'),
      code_verifier: verifier, redirect_uri: callback, resource: base + '/mcp',
    } })
    assert.equal(response.status(), 200)
    const token = await response.json()
    assert.equal(token.scope, 'finance:read', 'Unchecked transaction permission must not be granted')
    await page.goto(base + '/settings/mcp')
    await page.getByRole('button', { name: 'Verbindung widerrufen: Synthetic browser client', exact: true }).click()
    await page.getByRole('button', { name: 'Verbindung widerrufen: Synthetic browser client', exact: true }).waitFor({ state: 'detached' })
    const rejected = await page.request.post(base + '/mcp', { headers: { Authorization: `Bearer ${token.access_token}` },
      data: { jsonrpc: '2.0', id: 100, method: 'tools/list', params: {} } })
    assert.equal(rejected.status(), 401, 'UI revocation must invalidate actual protocol access')
  }
  assert.equal(pageErrors.length, 0)
  console.log('Live synthetic browser checks passed: auth, CSRF, finance dashboard, mobile layout and MCP settings/consent state.')
} catch {
  console.error('Live synthetic browser verification failed. Inspect locally without publishing browser traces or credentials.')
  process.exitCode = 1
} finally {
  await browser.close()
}
