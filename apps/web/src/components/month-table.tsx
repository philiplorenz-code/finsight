import { formatMoney, useLocale } from '../lib/i18n'
import { DataTable } from './ui'

export type Series = { months: string[]; income: Record<string, (string | number)[]>; expenses: (string | number)[]; surplus: (string | number)[] }

/** Concrete figures month by month, newest first: what actually came in and went out. No averages. */
export function MonthTable({ series, currency, limit = 12 }: { series?: Series; currency: string; limit?: number }) {
  const { language } = useLocale(); const de = language === 'de'
  if (!series?.months?.length) return null
  const n = series.months.length
  const rows = series.months.map((m, i) => ({
    month: m.slice(0, 7), salary: Number(series.income.employment?.[i] ?? 0), business: Number(series.income.business?.[i] ?? 0),
    other: Number(series.income.other?.[i] ?? 0), spent: Number(series.expenses[i] ?? 0), surplus: Number(series.surplus[i] ?? 0),
  })).slice(Math.max(0, n - limit)).reverse()
  const money = (v: number) => v ? formatMoney(String(v), currency, language).replace(/,00(?=\s)/, '') : '–'
  const label = (m: string) => new Intl.DateTimeFormat(de ? 'de-DE' : 'en-GB', { month: 'short', year: '2-digit' }).format(new Date(`${m}-01T00:00:00`))
  return <div className="table-scroll"><DataTable headers={[de ? 'Monat' : 'Month', de ? 'Gehalt' : 'Salary', de ? 'Nebengewerbe' : 'Business', de ? 'Sonstiges' : 'Other', de ? 'Ausgaben' : 'Spent', de ? 'Überschuss' : 'Surplus']}>
    {rows.map(r => <tr key={r.month}><td className="nowrap">{label(r.month)}</td><td className="nowrap num">{money(r.salary)}</td><td className="nowrap num">{money(r.business)}</td><td className="nowrap num">{money(r.other)}</td><td className="nowrap num">{money(r.spent)}</td><td className={`nowrap num ${r.surplus < 0 ? 'negative' : ''}`}>{money(r.surplus)}</td></tr>)}
  </DataTable></div>
}
