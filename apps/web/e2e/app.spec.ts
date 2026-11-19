import { expect, test, type Page } from '@playwright/test'

const account = { id: 'synthetic-account', name: 'Synthetic checking', currency: 'EUR', balance: '1234.56', balance_date: '2026-11-01', included: true, purpose: 'checking', ownership: 'owned', inactive: false }
const transaction = { id: 'synthetic-transaction', account_id: account.id, merchant: 'Synthetic merchant', amount: '-12.50', currency: 'EUR', booking_date: '2026-11-01', category: 'Food', source: { synthetic: true }, tags: [] }
async function mocks(page: Page, authenticated = true, initialized = true) {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api', '')
    let data: unknown = []
    if (path === '/auth/status') data = { initialized, authenticated }
    else if (path === '/auth/me') data = { id: 'owner', email: 'synthetic@example.invalid', csrf_token: 'synthetic-csrf' }
    else if (path === '/overview') data = { currencies: [], categories: [], trends: [], warnings: [] }
    else if (path === '/accounts') data = [account]
    else if (path.endsWith('/balances')) data = [{ observed_date: '2026-11-01', amount: '1234.56' }]
    else if (path === '/transactions') data = { items: [transaction], total: 1, page: 1, page_size: 25 }
    else if (path === `/transactions/${transaction.id}`) data = transaction
    else if (path === '/contracts') data = { items: [{ name: 'Synthetic insurance', currency: 'EUR', source: 'source', confidence: 'confirmed', period: 'yearly', annual_cost: '720.00', evidence: [transaction.id] }] }
    else if (path === '/ai/usage') data = { currency: 'EUR', runs: [] }
    else if (path === '/settings') data = { ai_enabled: false, external_ai_consent: false }
    await route.fulfill({ status: 200, json: data })
  })
}

test('secure login uses email and same-origin session, then obtains CSRF', async ({ page }) => {
  await mocks(page, false)
  let authenticated = false
  await page.route('**/api/auth/status', route => route.fulfill({ json: { initialized: true, authenticated } }))
  await page.route('**/api/auth/login', async route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().postDataJSON()).toEqual({ email: 'synthetic@example.invalid', password: 'synthetic-password' })
    authenticated = true
    await route.fulfill({ json: { id: 'owner', email: 'synthetic@example.invalid', csrf_token: 'synthetic-csrf' } })
  })
  await page.goto('/')
  await page.getByLabel('E-Mail').fill('synthetic@example.invalid')
  await page.getByLabel('Passwort', { exact: true }).fill('synthetic-password')
  await page.getByRole('button', { name: 'Anmelden' }).click()
  await expect(page.getByRole('heading', { name: 'Dein Geld. Im Überblick.' })).toBeVisible()
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }))
  expect(stored).not.toContain('synthetic-password'); expect(stored).not.toContain('synthetic-csrf')
})

test('bootstrap is secret gated and password is masked', async ({ page }) => {
  await mocks(page, false, false)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'FinSight einrichten' })).toBeVisible()
  await expect(page.getByLabel('Bootstrap-Secret')).toHaveAttribute('type', 'password')
  await expect(page.getByLabel('Passwort', { exact: true })).toHaveAttribute('minlength', '12')
})

test('login failure is generic and never leaks server error strings', async ({ page }) => {
  await mocks(page, false)
  await page.route('**/api/auth/login', route => route.fulfill({ status: 401, json: { detail: 'PRIVATE-SERVER-SECRET' } }))
  await page.goto('/')
  await page.getByLabel('E-Mail').fill('synthetic@example.invalid')
  await page.getByLabel('Passwort', { exact: true }).fill('synthetic-password')
  await page.getByRole('button', { name: 'Anmelden' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Passwort', { exact: true })).toHaveValue('')
  await expect(page.locator('body')).not.toContainText('PRIVATE-SERVER-SECRET')
})

test('overview is honest when empty and has no horizontal overflow', async ({ page }) => {
  await mocks(page); await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Hier ist noch Platz für Klarheit.' })).toBeVisible()
  await expect(page.locator('.stats-grid')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('overview displays currency-separated API totals and periods', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/overview?**', route => route.fulfill({ json: { currencies: [{ currency: 'EUR', income: '2500.00', expenses: '1500.00', surplus: '1000.00', observed_balance: '-100.00', savings_rate: '0.4' }, { currency: 'USD', income: '9000.00' }], trends: [], categories: [], warnings: ['Synthetic incomplete coverage'] } }))
  await page.goto('/')
  await expect(page.locator('.stats-grid')).toContainText('2.500,00')
  await expect(page.locator('.stats-grid')).not.toContainText('9.000,00')
  await expect(page.getByText('40 %')).toBeVisible()
  await page.getByRole('button', { name: 'Letzte 3 Monate' }).click()
  await expect(page.getByRole('button', { name: 'Letzte 3 Monate' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('combobox', { name: 'Währung' }).selectOption('USD')
  await expect(page.locator('.stats-grid')).toContainText('9.000,00')
})

test('account edits carry CSRF and preserve source identity', async ({ page }) => {
  await mocks(page)
  let body: Record<string, unknown> = {}
  await page.route(`**/api/accounts/${account.id}`, async route => {
    expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf')
    body = route.request().postDataJSON()
    await route.fulfill({ json: { ...account, ...body } })
  })
  await page.goto('/accounts')
  await page.getByRole('button', { name: `Bearbeiten: ${account.name}` }).click()
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Renamed synthetic')
  await page.getByRole('button', { name: 'Speichern', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(body.name).toBe('Renamed synthetic'); expect(body).not.toHaveProperty('source_key')
})

test('transaction detail supports reversible corrections and escapes source values', async ({ page }) => {
  await mocks(page)
  await page.route(`**/api/transactions/${transaction.id}`, route => route.request().method() === 'PATCH'
    ? route.fulfill({ json: { ...transaction, category_override: route.request().postDataJSON().category_override } })
    : route.fulfill({ json: { ...transaction, source: { note: '<img src=x onerror=alert(1)>' } } }))
  await page.route(`**/api/transactions/${transaction.id}/reset`, route => route.fulfill({ json: transaction }))
  await page.goto(`/transactions?detail=${transaction.id}`)
  await page.getByRole('dialog').getByLabel('Kategorie', { exact: true }).fill('Synthetic correction')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= (visualViewport?.width || innerWidth) + 1)).toBe(true)
  const corrected = page.waitForRequest(r => r.method() === 'PATCH' && r.url().endsWith(transaction.id))
  await page.getByRole('button', { name: 'Speichern', exact: true }).click()
  expect((await corrected).postDataJSON().category_override).toBe('Synthetic correction')
  await page.getByText('Originalwerte', { exact: true }).click()
  await expect(page.getByRole('dialog').locator('img')).toHaveCount(0)
  const reset = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith('/reset'))
  await page.getByRole('button', { name: 'Korrektur zurücksetzen' }).click()
  await reset
})

test('synthetic upload requires preview before importing', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/imports/preview', async route => {
    expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf')
    await route.fulfill({ json: { row_count: 2, columns: ['Synthetic column'], warnings: [] } })
  })
  await page.route('**/api/imports', route => route.fulfill({ json: route.request().method() === 'POST' ? { id: 'synthetic-import', status: 'completed' } : [] }))
  await page.goto('/imports')
  await expect(page.getByRole('button', { name: 'Import starten' })).toHaveCount(0)
  await page.locator('input[type=file]').setInputFiles({ name: 'synthetic.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('SYNTHETIC MOCK ONLY - NOT A REAL WORKBOOK') })
  await page.getByRole('button', { name: 'Vorschau prüfen' }).click()
  await expect(page.getByText('Synthetic column')).toBeVisible()
  await page.getByRole('button', { name: 'Import starten' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Gespeichert.' })).toBeVisible()
})

test('bucket creation sends decimal strings', async ({ page }) => {
  await mocks(page)
  await page.goto('/buckets')
  await page.getByRole('button', { name: 'Spartopf erstellen' }).click()
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Synthetic annual reserve')
  await page.getByLabel('Zielbetrag').fill('720.00')
  const request = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith('/buckets'))
  await page.getByRole('dialog').getByRole('button', { name: 'Spartopf erstellen' }).click()
  expect((await request).postDataJSON().target).toBe('720.00')
})

test('contracts expose resolvable evidence', async ({ page }) => {
  await mocks(page); await page.goto('/contracts')
  await page.getByRole('button', { name: 'Details: Synthetic insurance' }).click()
  await expect(page.getByRole('dialog').getByRole('link', { name: 'Buchungen →' })).toHaveAttribute('href', `/transactions?detail=${transaction.id}`)
})

test('language and theme persist without storing financial data', async ({ page }) => {
  await mocks(page); await page.goto('/settings')
  await page.getByRole('combobox', { name: 'Sprache' }).selectOption('en')
  await page.locator('.settings-appearance').getByRole('button', { name: 'Dark', exact: true }).click()
  await expect(page.locator('html')).toHaveClass('dark')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
  await expect(page.locator('html')).toHaveClass('dark')
  expect(await page.evaluate(() => Object.keys(localStorage).sort())).toEqual(['finsight-language', 'finsight-theme'])
})

test('API errors offer retry rather than fake rows', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/accounts', route => route.fulfill({ status: 503, json: { detail: 'PRIVATE-SERVER-SECRET' } }))
  await page.goto('/accounts')
  await expect(page.getByRole('heading', { name: 'Die Daten konnten nicht geladen werden.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Erneut versuchen' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('PRIVATE-SERVER-SECRET')
})

test('CSRF rejection never reports a successful account mutation', async ({ page }) => {
  await mocks(page)
  await page.route(`**/api/accounts/${account.id}`, route => route.fulfill({ status: 403, json: { detail: 'sensitive-internal-detail' } }))
  await page.goto('/accounts')
  await page.getByRole('button', { name: `Bearbeiten: ${account.name}` }).click()
  await page.getByRole('button', { name: 'Speichern', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Sicherheitsprüfung fehlgeschlagen')
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('sensitive-internal-detail')
})

test('bucket funding replaces allocations atomically with string amounts', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/buckets', route => route.fulfill({ json: [{ id: 'synthetic-bucket', name: 'Annual reserve', currency: 'EUR', kind: 'virtual', target: '720.00', funded: '120.00', required_monthly_contribution: '50.00', allocations: [{ account_id: account.id, amount: '120.00' }], obligations: [] }] }))
  await page.goto('/buckets')
  await page.getByRole('button', { name: 'Geld zuordnen' }).click()
  await page.getByRole('dialog').getByLabel(`${account.name} · EUR`).fill('150.00')
  const request = page.waitForRequest(r => r.method() === 'PUT' && r.url().endsWith('/allocations'))
  await page.getByRole('button', { name: 'Speichern', exact: true }).click()
  expect((await request).postDataJSON()).toEqual({ allocations: [{ account_id: account.id, amount: '150.00' }] })
})

test('AI stays disabled without consent and ntfy settings use the real nested contract', async ({ page }) => {
  await mocks(page)
  await page.goto('/insights')
  await expect(page.getByRole('button', { name: 'Fragen', exact: true })).toBeDisabled()
  await page.goto('/settings')
  await page.getByLabel('ntfy-Server (HTTPS)').fill('https://ntfy.example.invalid')
  await page.getByLabel('Privates Topic').fill('synthetic-topic')
  await page.getByLabel('Ruhezeit von').fill('21:30')
  const request = page.waitForRequest(r => r.method() === 'PATCH' && r.url().endsWith('/settings'))
  await page.getByRole('button', { name: 'Speichern', exact: true }).click()
  const body = (await request).postDataJSON()
  expect(body.notifications.server).toBe('https://ntfy.example.invalid')
  expect(body.notifications.quiet_start).toBe(1290)
  expect(body.ai.enabled).toBe(false); expect(body.ai.external_consent).toBe(false)
})

test('responsive navigation is keyboard dismissible and focus returns to the opener', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'Drawer is mobile-only')
  await mocks(page); await page.goto('/')
  const opener = page.getByRole('button', { name: 'Menü öffnen' })
  await opener.click()
  await expect(page.getByRole('navigation', { name: 'DEINE FINANZEN' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(opener).toBeFocused()
  await expect(opener).toHaveAttribute('aria-expanded', 'false')
})

test('cashflow and category charts expose real API values and a text alternative', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/overview?**', route => route.fulfill({ json: {
    currencies: [{ currency: 'EUR', income: '100.00', expenses: '40.00', surplus: '60.00', savings_rate: '0.6' }],
    trends: [{ month: '2026-11', currency: 'EUR', income: '100.00', expenses: '40.00' }],
    categories: [{ currency: 'EUR', category: 'Synthetic category', amount: '40.00' }], warnings: [],
  } }))
  await page.goto('/')
  await expect(page.locator('.recharts-pie-sector').first()).toBeVisible()
  await expect(page.locator('.category-list')).toContainText('Synthetic category')
  await page.locator('.chart-accessible summary').click()
  await expect(page.locator('.chart-accessible table')).toContainText('100,00')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= (visualViewport?.width || innerWidth) + 1)).toBe(true)
})

test('populated charts stay inside the viewport after desktop-to-mobile resize', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mocks(page)
  await page.route('**/api/overview?**', route => route.fulfill({ json: {
    currencies: [{ currency: 'EUR', income: '100.00', expenses: '40.00', surplus: '60.00', savings_rate: '0.6' }],
    trends: [{ month: '2026-11', currency: 'EUR', income: '100.00', expenses: '40.00' }],
    categories: [{ currency: 'EUR', category: 'Synthetic category', amount: '40.00' }], warnings: [],
  } }))
  await page.goto('/')
  await expect(page.locator('.recharts-pie-sector').first()).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth + 1 && [...document.querySelectorAll('.recharts-wrapper')].every(element => element.getBoundingClientRect().right <= innerWidth + 1))
  await expect(page.locator('.chart-container')).toHaveCSS('height', '240px')
  await expect(page.locator('.donut-container')).toHaveCSS('height', '200px')
  const png = await page.screenshot({ fullPage: true, scale: 'css' })
  // PNG IHDR width: catches screenshot surfaces widened by stale chart measurements.
  expect(png.readUInt32BE(16)).toBe(390)
})

for (const theme of ['light', 'dark']) {
  test(`chart SVG viewports remain nonzero with many categories in ${theme} mode`, async ({ page }) => {
    await mocks(page)
    await page.addInitScript(value => localStorage.setItem('finsight-theme', value), theme)
    await page.route('**/api/overview?**', route => route.fulfill({ json: {
      currencies: [{ currency: 'EUR', income: '1860.00', expenses: '930.00', surplus: '930.00', savings_rate: '0.5' }],
      trends: Array.from({ length: 12 }, (_, index) => ({ month: `2026-${String(index + 1).padStart(2, '0')}`, currency: 'EUR', income: String(100 + index * 10), expenses: String(50 + index * 5) })),
      categories: Array.from({ length: 60 }, (_, index) => ({ currency: 'EUR', category: `Synthetic category ${index + 1}`, amount: '15.50' })),
      warnings: [],
    } }))
    await page.goto('/')
    await expect(page.locator('.category-list li')).toHaveCount(60)
    // A sector's geometry can exist even when a zero-width SVG clips all paint.
    for (const selector of ['.chart-container', '.donut-container']) {
      await expect.poll(async () => (await page.locator(`${selector} svg.recharts-surface`).boundingBox())?.width || 0).toBeGreaterThan(200)
      await expect.poll(async () => (await page.locator(`${selector} svg.recharts-surface`).boundingBox())?.height || 0).toBeGreaterThan(150)
    }
    await expect(page.locator('.chart-container .recharts-area-curve').first()).toBeVisible()
    await expect(page.locator('.donut-container .recharts-pie-sector').first()).toBeVisible()
    const list = page.getByRole('region', { name: 'Ausgabenkategorien' })
    await expect(list).toHaveAttribute('tabindex', '0')
    expect(await list.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
    expect((await list.boundingBox())!.height).toBeLessThanOrEqual(320)
    await list.focus()
    await page.keyboard.press('End')
    await expect(page.getByText('Synthetic category 60', { exact: true })).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  })
}

test('large table amounts retain exact decimal cents in the browser', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/transactions?**', route => route.fulfill({ json: { items: [{ ...transaction, amount: '123456789012345.67' }], total: 1 } }))
  await page.goto('/transactions')
  await expect(page.locator('tbody .money')).toHaveText('123.456.789.012.345,67\u00a0€')
})

test('historical AI charges preserve USD and unknown currencies rather than assuming EUR', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/ai/usage', route => route.fulfill({ json: { currency: 'EUR', runs: [
    { id: 'old-usd', state: 'settled', currency: 'USD', reserved: '12.50', charged: '12.50' },
    { id: 'old-null', state: 'uncertain', currency: null, reserved: '1.23', charged: null },
    { id: 'old-absent', state: 'uncertain', reserved: '4.56', charged: null },
    { id: 'new-eur', state: 'settled', currency: 'EUR', reserved: '0.25', charged: '0.20' },
  ] } }))
  await page.goto('/insights')
  const usd = page.locator('tr').filter({ hasText: 'USD · legacy' })
  await expect(usd).toContainText('12,50')
  await expect(usd).not.toContainText('€')
  const unknown = page.locator('tr').filter({ hasText: 'Währung unbekannt' })
  await expect(unknown).toHaveCount(2)
  await expect(unknown.first()).toContainText('1.23 / —')
  await expect(unknown.first()).not.toContainText('€')
  await expect(page.locator('tr').filter({ hasText: '0,25' })).toContainText('€')
})

test('legacy AI policy is blocked from silently becoming an EUR policy', async ({ page }) => {
  await mocks(page)
  await page.route('**/api/settings', route => route.fulfill({ json: { ai: { budget_currency: 'USD', monthly_limit: '12.50' } } }))
  await page.goto('/settings')
  await expect(page.getByText(/Historische KI-Richtlinie/)).toContainText('USD')
  await expect(page.getByLabel('Monatliches Limit (EUR)', { exact: true })).toHaveCount(0)
  const revoke = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith('/ai/consent'))
  await page.getByRole('button', { name: 'KI-Zustimmung widerrufen' }).click()
  expect((await revoke).postDataJSON()).toEqual({ enabled: false, external_consent: false, proactive_consent: false })
})

test('explicit consent provisions the operator policy without sending provider secrets', async ({ page }) => {
  await mocks(page)
  await page.goto('/settings')
  await page.getByRole('checkbox', { name: 'KI aktivieren', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Ich stimme der externen Verarbeitung minimierter Finanzaggregate zu.', exact: true }).check()
  const request = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith('/ai/consent'))
  await page.getByRole('button', { name: 'Serverkonfiguration mit Zustimmung übernehmen' }).click()
  expect((await request).postDataJSON()).toEqual({ enabled: true, external_consent: true, proactive_consent: false })
})

test('historical as-of and custom-date controls keep their stable labels', async ({ page }) => {
  await mocks(page); await page.goto('/')
  await page.getByRole('button', { name: 'Historischer Stichtag', exact: true }).click()
  const historical = page.waitForRequest(r => r.url().includes('/api/overview?start=2024-02-01&end=2024-02-29'))
  await page.getByLabel('Stichtag', { exact: true }).fill('2024-02-29')
  await historical
  await expect(page.getByText(/Aktuelle Zuordnungen sind keine historischen Fakten/)).toBeVisible()
  await page.getByRole('button', { name: 'Eigener Zeitraum', exact: true }).click()
  await expect(page.getByLabel('Von', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Bis', { exact: true })).toBeVisible()
})
