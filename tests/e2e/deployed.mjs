/** Real browser + shipped proxy + live API. Isolated synthetic installation only. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
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
  console.log('Live synthetic browser checks passed: same-origin login, cookie session, CSRF rejection, API data and dashboard rendering.')
} catch {
  console.error('Live synthetic browser verification failed. Inspect locally without publishing browser traces or credentials.')
  process.exitCode = 1
} finally {
  await browser.close()
}
