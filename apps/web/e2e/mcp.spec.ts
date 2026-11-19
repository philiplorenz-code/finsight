import { expect, test, type Page } from '@playwright/test'

const id = '00000000-0000-4000-8000-000000000001'
const consentUrl = `/mcp/authorize?request_id=${id}`
const request = { id, client_id: 'synthetic-client', client_name: 'Synthetic Chat', redirect_uri: 'https://client.example.invalid/callback', scopes: ['finance:read', 'finance:transactions'], resource: 'https://finance.example.invalid/mcp', expires_at: '2099-01-01T00:00:00Z' }

async function mocks(page: Page, authenticated = true) {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/status') return route.fulfill({ json: { authenticated, initialized: true } })
    if (path === '/api/auth/me') return route.fulfill({ json: { csrf_token: 'synthetic-csrf' } })
    if (path === `/api/mcp/authorization-requests/${id}`) return route.fulfill({ json: request })
    return route.fulfill({ status: 503, json: { detail: 'PRIVATE-ERROR' } })
  })
}

for (const language of ['de', 'en']) {
  test(`MCP spoofed trusted name exposes inert callback origin and resource (${language})`, async ({ page }) => {
    await page.addInitScript(language => localStorage.setItem('finsight-language', language), language)
    await mocks(page)
    const callback = `https://attacker.example.invalid/callback/${'untrusted'.repeat(80)}?state=synthetic`
    const resource = `https://finance.example.invalid/mcp?synthetic=${'resource'.repeat(50)}`
    let metadataFetches = 0
    await page.route('https://attacker.example.invalid/**', route => { metadataFetches++; return route.abort() })
    await page.route('https://finance.example.invalid/**', route => { metadataFetches++; return route.abort() })
    await page.route(`**/api/mcp/authorization-requests/${id}`, route => route.fulfill({ json: { ...request, client_name: 'ChatGPT', redirect_uri: callback, resource } }))
    await page.goto(consentUrl)
    await expect(page.getByRole('heading', { name: 'ChatGPT', exact: true })).toBeVisible()
    await expect(page.getByText(language === 'de' ? /Client-Name ist selbst angegeben und nicht von FinSight verifiziert/ : /client name is self-asserted and not verified by FinSight/)).toBeVisible()
    await expect(page.getByTestId('mcp-callback-origin')).toHaveText('https://attacker.example.invalid')
    await expect(page.getByTestId('mcp-callback-uri')).toHaveText(callback)
    await expect(page.getByTestId('mcp-resource')).toHaveText(resource)
    await expect(page.locator('.mcp-destinations a, .mcp-destinations img, .mcp-destinations iframe')).toHaveCount(0)
    await expect(page.getByRole('checkbox', { name: language === 'de' ? /Ich habe geprüft, dass die registrierte Callback-Origin https:\/\/attacker.example.invalid/ : /I have checked that the registered callback origin https:\/\/attacker.example.invalid/ })).not.toBeChecked()
    await expect(page.getByRole('button', { name: language === 'de' ? 'Zugriff ausdrücklich erlauben' : 'Explicitly allow access' })).toBeDisabled()
    await page.setViewportSize({ width: 390, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(metadataFetches).toBe(0)
  })
}

for (const approved of [true, false]) {
  test(`MCP ${approved ? 'approval requires explicit consent' : 'denial needs no consent'} and preserves CSRF`, async ({ page }) => {
    await mocks(page)
    await page.route('https://client.example.invalid/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>Synthetic client callback</h1>' }))
    let body: unknown
    await page.route(`**/api/mcp/authorization-requests/${id}/decision`, async route => {
      expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf')
      body = route.request().postDataJSON()
      await route.fulfill({ json: { redirect_url: `https://client.example.invalid/callback?${approved ? 'code=synthetic' : 'error=access_denied'}` } })
    })
    await page.goto(consentUrl)
    await expect(page.getByRole('heading', { name: 'Synthetic Chat' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Zugriff ausdrücklich erlauben' })).toBeDisabled()
    await expect(page.getByText(/FinSight-KI-Budget deckt keine LLM-Kosten/)).toBeVisible()
    if (approved) await page.getByLabel('Ich stimme der Übermittlung', { exact: false }).check()
    await page.getByRole('button', { name: approved ? 'Zugriff ausdrücklich erlauben' : 'Ablehnen', exact: true }).click()
    await expect(page).toHaveURL(/https:\/\/client.example.invalid\/callback/)
    expect(body).toEqual({ decision: approved ? 'allow' : 'deny', scopes: approved ? ['finance:read'] : [] })
  })
}

test('MCP detailed transactions require separate opt-in', async ({ page }) => {
  await mocks(page)
  await page.route(`**/api/mcp/authorization-requests/${id}/decision`, async route => {
    expect(route.request().postDataJSON()).toEqual({ decision: 'allow', scopes: ['finance:read', 'finance:transactions'] })
    await route.fulfill({ json: { redirect_url: 'javascript:alert(1)' } })
  })
  await page.goto(consentUrl)
  await page.getByLabel('Optional: detaillierte Buchungen', { exact: false }).check()
  await page.getByLabel('Ich stimme der Übermittlung', { exact: false }).check()
  await page.getByRole('button', { name: 'Zugriff ausdrücklich erlauben' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(consentUrl)
})

for (const redirect of ['javascript:alert(1)', 'http://evil.example.invalid/callback', '//evil.example.invalid']) {
  test(`MCP never follows unsafe server redirect ${redirect}`, async ({ page }) => {
    await mocks(page)
    await page.route(`**/api/mcp/authorization-requests/${id}/decision`, route => route.fulfill({ json: { redirect_url: redirect } }))
    await page.goto(consentUrl)
    await page.getByRole('button', { name: 'Ablehnen', exact: true }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page).toHaveURL(consentUrl)
  })
}

test('MCP authorization stays behind login and retains the original URL', async ({ page }) => {
  await mocks(page, false)
  let requested = false
  let authenticated = false
  await page.route('**/api/auth/status', route => route.fulfill({ json: { initialized: true, authenticated } }))
  await page.route(`**/api/mcp/authorization-requests/${id}`, route => { requested = true; return route.fulfill({ json: request }) })
  await page.route('**/api/auth/login', route => { authenticated = true; return route.fulfill({ json: { csrf_token: 'synthetic-csrf' } }) })
  await page.goto(consentUrl)
  await expect(page.getByRole('heading', { name: 'Anmelden' })).toBeVisible()
  expect(requested).toBe(false)
  await expect(page).toHaveURL(consentUrl)
  await page.getByLabel('E-Mail').fill('synthetic@example.invalid')
  await page.getByLabel('Passwort', { exact: true }).fill('synthetic-password')
  await page.getByRole('button', { name: 'Anmelden' }).click()
  await expect(page.getByRole('heading', { name: 'Synthetic Chat' })).toBeVisible()
  await expect(page).toHaveURL(consentUrl)
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toContain('synthetic-csrf')
})

test('MCP revocation is independent of unavailable AI forms and refreshes the list', async ({ page }) => {
  await mocks(page)
  let revoked = false
  await page.route('**/api/mcp/connections', route => route.fulfill({ json: { enabled: false, endpoint: 'https://finance.example.invalid/mcp', scopes: ['finance:read'], connections: revoked ? [] : [{ id, client_name: 'Synthetic Chat', scopes: ['finance:read'], created_at: '2026-01-01T00:00:00Z' }] } }))
  await page.route(`**/api/mcp/connections/${id}`, async route => {
    expect(route.request().method()).toBe('DELETE')
    expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf')
    revoked = true
    await route.fulfill({ json: { ok: true } })
  })
  await page.goto('/settings')
  await page.getByRole('link', { name: 'MCP-Verbindungen verwalten' }).click()
  await expect(page.getByText('Server deaktiviert', { exact: true })).toBeVisible()
  await expect(page.getByLabel('MCP-Endpunkt')).toHaveValue('https://finance.example.invalid/mcp')
  await page.getByRole('button', { name: 'Verbindung widerrufen: Synthetic Chat' }).click()
  await expect(page.getByText('Keine freigegebenen Verbindungen.')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('MCP invalid request IDs are rejected locally and expired requests cannot be approved', async ({ page }) => {
  await mocks(page)
  let requests = 0
  await page.route('**/api/mcp/authorization-requests/**', route => { requests++; return route.fulfill({ json: { ...request, expires_at: '2000-01-01T00:00:00Z' } }) })
  await page.goto('/mcp/authorize?request_id=invalid&redirect_url=javascript:alert(1)')
  await expect(page.getByText(/Ungültige oder fehlende Anfrage-ID/)).toBeVisible()
  expect(requests).toBe(0)
  await page.goto(consentUrl)
  await expect(page.getByText(/Die Anfrage ist abgelaufen/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Zugriff ausdrücklich erlauben' })).toBeDisabled()
})
