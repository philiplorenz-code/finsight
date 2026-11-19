import { expect, test, type Page } from '@playwright/test'

async function mockTransactions(page: Page) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const json = path === '/api/auth/status' ? { initialized: true, authenticated: true }
      : path === '/api/auth/me' ? { csrf_token: 'synthetic-csrf' }
        : path === '/api/accounts' ? [{ id: 'synthetic-account', name: 'Synthetic checking', currency: 'EUR' }]
          : { items: [], total: 0 }
    return route.fulfill({ json })
  })
}

test('MCP transaction link hydrates canonical dates, view, currency and optional filters', async ({ page }) => {
  await mockTransactions(page)
  const fetched = page.waitForRequest(request => new URL(request.url()).pathname === '/api/transactions')
  await page.goto('/transactions?start=2026-01-01&end=2026-01-31&currency=EUR&view=included_spending&category=Food&account_id=synthetic-account')
  const params = new URL((await fetched).url()).searchParams
  await expect(page.getByLabel('Von', { exact: true })).toHaveValue('2026-01-01')
  await expect(page.getByLabel('Bis', { exact: true })).toHaveValue('2026-01-31')
  await expect(page.getByLabel('Buchungsansicht')).toHaveValue('included_spending')
  await expect(page.getByLabel('Währung', { exact: true })).toHaveValue('EUR')
  await expect(page.getByLabel('Kategorie', { exact: true })).toHaveValue('Food')
  await expect(page.getByRole('combobox', { name: 'Konto', exact: true })).toHaveValue('synthetic-account')
  expect(Object.fromEntries(params)).toMatchObject({ start: '2026-01-01', end: '2026-01-31', view: 'included_spending', currency: 'EUR', category: 'Food', account_id: 'synthetic-account' })
  await page.getByRole('button', { name: 'Filter', exact: true }).click()
  await expect(page.getByLabel('Buchungsansicht')).toBeVisible()
  await expect(page.getByLabel('Währung', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('legacy aliases hydrate and editing removes equivalent aliases and resets pagination', async ({ page }) => {
  await mockTransactions(page)
  await page.goto('/transactions?date_from=2026-02-01&date_to=2026-02-28&amount_min=10&contract_id=synthetic-contract&page=3')
  await expect(page.getByLabel('Von', { exact: true })).toHaveValue('2026-02-01')
  await expect(page.getByLabel('Bis', { exact: true })).toHaveValue('2026-02-28')
  const changed = page.waitForRequest(request => {
    const url = new URL(request.url())
    return url.pathname === '/api/transactions' && url.searchParams.get('start') === '2026-02-02'
  })
  await page.getByLabel('Von', { exact: true }).fill('2026-02-02')
  const apiParams = new URL((await changed).url()).searchParams
  expect(apiParams.getAll('start')).toEqual(['2026-02-02'])
  expect(apiParams.get('end')).toBe('2026-02-28')
  expect(apiParams.get('min_amount')).toBe('10')
  expect(apiParams.get('contract')).toBe('synthetic-contract')
  expect(apiParams.has('date_from')).toBe(false)
  expect(apiParams.has('date_to')).toBe(false)
  expect(apiParams.get('page')).toBe('1')
  await expect.poll(() => new URL(page.url()).searchParams.has('date_from')).toBe(false)
  expect(new URL(page.url()).searchParams.has('page')).toBe(false)
  await page.getByLabel('Bis', { exact: true }).fill('2026-02-27')
  await expect.poll(() => new URL(page.url()).searchParams.get('end')).toBe('2026-02-27')
  expect(new URL(page.url()).searchParams.has('date_to')).toBe(false)
})

test('canonical dates win collisions regardless of alias order and clearing cannot resurrect aliases', async ({ page }) => {
  await mockTransactions(page)
  const fetched = page.waitForRequest(request => new URL(request.url()).pathname === '/api/transactions')
  await page.goto('/transactions?start=2026-03-01&date_from=2020-01-01&date_to=2020-01-31&end=2026-03-31')
  const params = new URL((await fetched).url()).searchParams
  expect(params.getAll('start')).toEqual(['2026-03-01'])
  expect(params.getAll('end')).toEqual(['2026-03-31'])
  await expect(page.getByLabel('Von', { exact: true })).toHaveValue('2026-03-01')
  await expect(page.getByLabel('Bis', { exact: true })).toHaveValue('2026-03-31')
  const cleared = page.waitForRequest(request => {
    const url = new URL(request.url())
    return url.pathname === '/api/transactions' && !url.searchParams.has('start')
  })
  await page.getByLabel('Von', { exact: true }).fill('')
  const clearedParams = new URL((await cleared).url()).searchParams
  expect(clearedParams.has('date_from')).toBe(false)
  await expect(page.getByLabel('Von', { exact: true })).toHaveValue('')
  const browserParams = new URL(page.url()).searchParams
  expect(browserParams.has('start')).toBe(false)
  expect(browserParams.has('date_from')).toBe(false)
})

test('view and currency stay visible and changes reach the API without stale dates', async ({ page }) => {
  await mockTransactions(page)
  await page.goto('/transactions')
  await expect(page.getByLabel('Buchungsansicht')).toHaveValue('all_transactions')
  await expect(page.getByLabel('Währung', { exact: true })).toHaveValue('')
  for (const view of ['included_spending', 'owned_liquid', 'all_transactions']) {
    const changed = page.waitForRequest(request => {
      const url = new URL(request.url())
      return url.pathname === '/api/transactions' && url.searchParams.get('view') === view
    })
    await page.getByLabel('Buchungsansicht').selectOption(view)
    const params = new URL((await changed).url()).searchParams
    expect(params.getAll('view')).toEqual([view])
    expect(params.has('start')).toBe(false)
    expect(params.has('end')).toBe(false)
  }
  const currencyChanged = page.waitForRequest(request => {
    const url = new URL(request.url())
    return url.pathname === '/api/transactions' && url.searchParams.get('currency') === 'USD'
  })
  await page.getByLabel('Währung', { exact: true }).fill('USD')
  expect(new URL((await currencyChanged).url()).searchParams.get('view')).toBe('all_transactions')
  await expect(page.getByLabel('Währung', { exact: true })).toHaveValue('USD')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
