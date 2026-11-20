import type { Bucket, Contract, Overview } from './types'

export type RawOverview = {
  currencies: { currency: string; income?: string; expenses?: string; surplus?: string; savings_rate?: string | null; observed_balance?: string; observed_mine?: string; held_for_others?: string; available_liquidity?: string; monthly_obligations?: string }[]
  categories?: { currency: string; category: string; amount: string }[]
  trends?: { month: string; currency: string; income: string; expenses: string }[]
  warnings?: string[]; start?: string; end?: string
}
export function overviewForCurrency(raw: RawOverview, currency: string): Overview {
  const values = raw.currencies?.find(c => c.currency === currency)
  return { ...values, savings_rate: values?.savings_rate == null ? null : new Intl.NumberFormat('en', { maximumFractionDigits: 1, useGrouping: false }).format(Number(values.savings_rate) * 100), currencies: raw.currencies?.map(c => c.currency), observed_net_worth: values?.observed_mine ?? values?.observed_balance, held_for_others: values?.held_for_others, fixed_obligations: values?.monthly_obligations, categories: raw.categories?.filter(c => c.currency === currency).map(c => ({ name: c.category, amount: c.amount })), trends: raw.trends?.filter(c => c.currency === currency), warnings: raw.warnings }
}
export function periodDates(period: string, from: string, to: string, now = new Date()) {
  // Calendar dates in the installation's default time zone, not UTC slicing.
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  const get = (type: string) => Number(parts.find(p => p.type === type)?.value)
  const year = get('year'); const month = get('month')
  if (period === 'custom') return { start: from, end: to }
  if (period === 'asof') return { start: `${to.slice(0, 7)}-01`, end: to }
  const months = period === 'quarter' ? 3 : period === 'sixmonths' ? 6 : period === 'twelvemonths' ? 12 : period === 'lastmonth' ? 2 : 1
  const start = new Date(Date.UTC(year, period === 'year' ? 0 : month - months, 1))
  const end = period === 'lastmonth' ? new Date(Date.UTC(year, month - 1, 0)).toISOString().slice(0, 10) : `${year}-${String(month).padStart(2, '0')}-${String(get('day')).padStart(2, '0')}`
  return { start: start.toISOString().slice(0, 10), end }
}
export type RawBucket = Bucket & { target?: string; funded?: string; required_monthly_contribution?: string; goal?: { status: string; required_monthly: string; planned_monthly: string; months_left?: number | null; projected_at_due?: string | null; target: string } | null; warnings?: string[]; allocations?: { account_id: string; amount: string }[] }
export function normalizeBucket(b: RawBucket): RawBucket { return { ...b, target_amount: b.target, funded_amount: b.funded, required_monthly: b.required_monthly_contribution } }
export type RawContract = Omit<Contract, 'id' | 'evidence'> & { id?: string; period?: string; annual_cost?: string; evidence?: (string | { transaction_id?: string; description?: string })[] }
export function normalizeContract(c: RawContract, i: number): Contract { return { ...c, id: c.id || `${c.name}-${c.currency}-${i}`, frequency: c.period, annualized_cost: c.annual_cost, evidence: c.evidence?.map(e => typeof e === 'string' ? { transaction_id: e } : e) } }
