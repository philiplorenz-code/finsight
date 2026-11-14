import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Button, Dialog, Feedback, Money, QueryState } from '../components/ui'
import { LocaleProvider, formatDate, formatMoney } from '../lib/i18n'
import { overviewForCurrency, normalizeContract, periodDates } from '../lib/adapters'
import { ApiError } from '../lib/api'
describe('accessible localized components', () => {
  it('defaults to German and gives an honest missing-value display', () => {
    render(<LocaleProvider><Money value={undefined} /></LocaleProvider>)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(formatMoney('1234.56', 'EUR', 'de')).toContain('1.234,56')
    expect(formatMoney('invalid')).toBe('—')
    expect(formatDate('2026-11-14')).toContain('14.11.2026')
  })
  it('preserves cents in large decimal strings without a Number roundtrip', () => {
    expect(formatMoney('123456789012345.67', 'EUR', 'de')).toBe('123.456.789.012.345,67\u00a0€')
    expect(formatMoney('-123456789012345.67', 'EUR', 'en')).toBe('-€123,456,789,012,345.67')
    expect(formatMoney('999999999999999.99', 'EUR', 'de')).toContain('999.999.999.999.999,99')
    expect(formatMoney('1.005', 'EUR', 'de')).toContain('1,01')
  })
  it('renders empty state with a usable import link instead of metrics', () => {
    render(<MemoryRouter><QueryState pending={false} error={null} retry={vi.fn()} empty importLink><span>FAKE METRICS</span></QueryState></MemoryRouter>)
    expect(screen.getByRole('link', { name: /Daten importieren/ })).toHaveAttribute('href', '/imports')
    expect(screen.queryByText('FAKE METRICS')).not.toBeInTheDocument()
  })
  it('provides a retry action for a failed query', async () => {
    const retry = vi.fn()
    render(<QueryState pending={false} error={new Error()} retry={retry}>{null}</QueryState>)
    await userEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }))
    expect(retry).toHaveBeenCalledOnce()
  })
  it('never renders raw API error details', () => {
    render(<Feedback error={new ApiError(500, '<script>secret</script>')} />)
    expect(screen.getByRole('alert')).not.toHaveTextContent('secret')
  })
  it('disables busy actions and exposes a named modal', () => {
    render(<><Button busy>Speichern</Button><Dialog title="Kontodetails" onClose={vi.fn()}>Synthetic content</Dialog></>)
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled()
    expect(screen.getByRole('dialog', { name: 'Kontodetails' })).toBeInTheDocument()
  })
})
describe('contract adapters', () => {
  it('keeps currencies separate and uses server totals, including negatives', () => {
    const data = overviewForCurrency({ currencies: [{ currency: 'EUR', income: '100.00', observed_balance: '-25.00', savings_rate: '0.25' }, { currency: 'USD', income: '900.00' }], categories: [{ currency: 'EUR', category: 'Synthetic', amount: '75.00' }, { currency: 'USD', category: 'Other', amount: '100.00' }] }, 'EUR')
    expect(data.income).toBe('100.00'); expect(data.observed_net_worth).toBe('-25.00'); expect(data.savings_rate).toBe('25'); expect(data.categories).toEqual([{ name: 'Synthetic', amount: '75.00' }])
  })
  it('links source contract evidence without guessing transaction identities', () => {
    expect(normalizeContract({ name: 'Synthetic', currency: 'EUR', evidence: ['transaction-id'] }, 0).evidence).toEqual([{ transaction_id: 'transaction-id' }])
  })
  it('resolves named and custom periods to Berlin calendar dates', () => {
    expect(periodDates('quarter', '', '', new Date('2026-01-15T10:00:00Z'))).toEqual({ start: '2025-11-01', end: '2026-01-15' })
    expect(periodDates('custom', '2026-01-01', '2026-02-01')).toEqual({ start: '2026-01-01', end: '2026-02-01' })
  })
  it('handles previous month, multi-month windows and historical dates across year/leap boundaries', () => {
    const now = new Date('2026-01-15T10:00:00Z')
    expect(periodDates('lastmonth', '', '', now)).toEqual({ start: '2025-12-01', end: '2025-12-31' })
    expect(periodDates('sixmonths', '', '', now)).toEqual({ start: '2025-08-01', end: '2026-01-15' })
    expect(periodDates('twelvemonths', '', '', now)).toEqual({ start: '2025-02-01', end: '2026-01-15' })
    expect(periodDates('lastmonth', '', '', new Date('2024-03-02T10:00:00Z'))).toEqual({ start: '2024-02-01', end: '2024-02-29' })
    expect(periodDates('asof', '', '2024-02-29', now)).toEqual({ start: '2024-02-01', end: '2024-02-29' })
  })
})
