import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Printer } from 'lucide-react'
import { api } from '../lib/api'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'
import { Button, DataTable, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Row = { name: string; amount: string; previous: string; change: string; count?: number; category?: string | null }
type Month = { month: string; income: string | null; expenses: string | null; previous_income: string | null; previous_expenses: string | null }
type Review = {
  year: number; currency: string; running: boolean; until: string; compared_until: string
  income: string; expenses: string; surplus: string; savings_rate?: string | null
  previous: { income: string; expenses: string; surplus: string }
  categories: Row[]; merchants: Row[]; merchant_count: number; months: Month[]
  rising: Row[]; falling: Row[]; new_merchants: Row[]; gone_merchants: Row[]; priciest_month: string | null; years: number[]; data_since?: string | null
}

export default function YearPage() {
  const { language } = useLocale(); const de = language === 'de'
  const [year, setYear] = useState<number | null>(null)
  const [allMerchants, setAllMerchants] = useState(false)
  const query = useQuery({ queryKey: ['report', 'year', year], queryFn: () => api<Review>(`/reports/yearly${year ? `?year=${year}` : ''}`) })
  const r = query.data
  const money = (v?: string | number | null) => formatMoney(String(v ?? 0), r?.currency ?? 'EUR', language)
  const monthName = (m: string, style: 'long' | 'short' = 'long') => new Intl.DateTimeFormat(de ? 'de-DE' : 'en-GB', { month: style }).format(new Date(`${m}-01T00:00:00`))
  const delta = (now: string | number, before: string | number, inverse = false) => {
    const d = Number(now) - Number(before)
    if (Math.abs(d) < 0.5) return <small className="muted">±0</small>
    const good = inverse ? d < 0 : d > 0
    return <small className={good ? 'positive' : 'negative'}>{d > 0 ? '+' : ''}{money(d)}</small>
  }
  const prevLabel = r ? String(r.year - 1) : ''
  const chart = (r?.months ?? []).map(m => ({ name: monthName(m.month, 'short'), now: m.expenses == null ? null : Number(m.expenses), before: m.previous_expenses == null ? null : Number(m.previous_expenses) }))
  const merchants = allMerchants ? r?.merchants ?? [] : (r?.merchants ?? []).slice(0, 15)
  return <div className="report-page">
    <PageHeader title={de ? `Jahresrückblick${r ? ` ${r.year}` : ''}` : `Year in review${r ? ` ${r.year}` : ''}`}
      description={de ? 'Dein Jahr in konkreten Summen: nach Kategorie, Händler und Monat, jeweils neben dem Vorjahr.' : 'Your year in concrete sums by category, merchant and month, next to the year before.'}
      action={r && <div className="badge-row no-print">
        <div className="segmented" role="group" aria-label={de ? 'Jahr' : 'Year'}>
          {r.years.slice(-4).map(y => <button key={y} aria-pressed={y === r.year} onClick={() => setYear(y)}>{y}</button>)}
        </div>
        <Button variant="outline" onClick={() => window.print()}><Printer size={16} />{de ? 'Drucken / PDF' : 'Print / PDF'}</Button>
      </div>} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{r && <>
      {r.running && <Notice>{de
        ? `Das Jahr läuft noch. Verglichen wird bis ${formatDate(r.until, language)} mit demselben Zeitraum ${prevLabel} (bis ${formatDate(r.compared_until, language)}).`
        : `The year is still running. Compared up to ${formatDate(r.until, language)} with the same period of ${prevLabel}.`}</Notice>}
      {r.data_since && r.data_since > `${r.year - 1}-01-01` && <Notice warning>{de
        ? `Deine Buchungen beginnen am ${formatDate(r.data_since, language)}. Vorher fehlen Daten, deshalb ist der Vergleich mit ${prevLabel} nur bedingt aussagekräftig.`
        : `Your bookings start on ${formatDate(r.data_since, language)}; the comparison with ${prevLabel} is incomplete.`}</Notice>}
      <div className="stat-grid">
        <div className="detail-stat"><span>{de ? 'Einnahmen' : 'Income'}</span><strong>{money(r.income)}</strong>{delta(r.income, r.previous.income)}</div>
        <div className="detail-stat"><span>{de ? 'Ausgaben' : 'Expenses'}</span><strong>{money(r.expenses)}</strong>{delta(r.expenses, r.previous.expenses, true)}</div>
        <div className="detail-stat"><span>{de ? 'Überschuss' : 'Surplus'}</span><strong>{money(r.surplus)}</strong>{delta(r.surplus, r.previous.surplus)}</div>
        <div className="detail-stat"><span>{de ? 'Sparquote' : 'Savings rate'}</span><strong>{r.savings_rate != null ? `${Math.round(Number(r.savings_rate) * 100)} %` : '—'}</strong></div>
      </div>
      <small className="muted">{de ? `Veränderung zum Vorjahreszeitraum. ${prevLabel}: Einnahmen ${money(r.previous.income)}, Ausgaben ${money(r.previous.expenses)}.` : `Change vs. the same period of ${prevLabel}: income ${money(r.previous.income)}, expenses ${money(r.previous.expenses)}.`}</small>
      <Panel title={de ? 'Das Wichtigste' : 'Highlights'}>
        <ul className="report-highlights">
          {r.priciest_month && <li>{de ? 'Teuerster Monat' : 'Most expensive month'}: <strong>{monthName(r.priciest_month)}</strong> ({money(r.months.find(m => m.month === r.priciest_month)?.expenses)})</li>}
          {r.rising.map(c => <li key={`up-${c.name}`}>{c.name}: {money(c.amount)} {de ? 'statt' : 'instead of'} {money(c.previous)} ({delta(c.amount, c.previous, true)})</li>)}
          {r.falling.map(c => <li key={`down-${c.name}`}>{c.name}: {money(c.amount)} {de ? 'statt' : 'instead of'} {money(c.previous)} ({delta(c.amount, c.previous, true)})</li>)}
          {!!r.new_merchants.length && <li>{de ? `Neu ${r.year}` : `New in ${r.year}`}: {r.new_merchants.map(m => `${m.name} (${money(m.amount)})`).join(', ')}</li>}
          {!!r.gone_merchants.length && <li>{de ? `Nicht mehr seit ${prevLabel}` : `Gone since ${prevLabel}`}: {r.gone_merchants.map(m => `${m.name} (${prevLabel}: ${money(m.previous)})`).join(', ')}</li>}
        </ul>
      </Panel>
      <Panel title={de ? 'Ausgaben pro Monat' : 'Spending per month'}>
        <div className="chart-container" role="img" aria-label={de ? `Ausgaben pro Monat ${r.year} und ${prevLabel}` : 'Spending per month'}><ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" /><YAxis width={56} tickFormatter={v => `${Math.round(Number(v) / 100) / 10}k`} />
            <Tooltip formatter={v => money(Number(v))} /><Legend />
            <Bar isAnimationActive={false} name={prevLabel} dataKey="before" fill="#a9b4b0" />
            <Bar isAnimationActive={false} name={String(r.year)} dataKey="now" fill="#287a68" />
          </BarChart></ResponsiveContainer></div>
        <DataTable headers={[de ? 'Monat' : 'Month', de ? 'Ausgaben' : 'Expenses', prevLabel, de ? 'Einnahmen' : 'Income', prevLabel]}>
          {r.months.map(m => <tr key={m.month}><td><Link to={`/report?month=${m.month}`}>{monthName(m.month)}</Link></td>
            <td>{m.expenses == null ? '—' : <><Money value={m.expenses} currency={r.currency} /> {m.previous_expenses != null && !(r.running && m.month === r.until.slice(0, 7)) && delta(m.expenses, m.previous_expenses, true)}</>}</td>
            <td className="muted">{m.previous_expenses == null ? '—' : <Money value={m.previous_expenses} currency={r.currency} />}</td>
            <td>{m.income == null ? '—' : <Money value={m.income} currency={r.currency} />}</td>
            <td className="muted">{m.previous_income == null ? '—' : <Money value={m.previous_income} currency={r.currency} />}</td></tr>)}
        </DataTable>
      </Panel>
      <Panel title={de ? 'Ausgaben nach Kategorie' : 'Spending by category'}>
        <DataTable headers={[de ? 'Kategorie' : 'Category', String(r.year), prevLabel, de ? 'Veränderung' : 'Change']}>
          {r.categories.map(c => <tr key={c.name}><td>{c.name}</td><td><Money value={c.amount} currency={r.currency} /></td><td className="muted"><Money value={c.previous} currency={r.currency} /></td><td>{delta(c.amount, c.previous, true)}</td></tr>)}
        </DataTable>
      </Panel>
      <Panel title={de ? `Händler (${r.merchant_count})` : `Merchants (${r.merchant_count})`}>
        <DataTable headers={[de ? 'Händler' : 'Merchant', String(r.year), prevLabel, de ? 'Veränderung' : 'Change']}>
          {merchants.map(m => <tr key={m.name}><td>{m.name}<div className="small muted">{m.count ? `${m.count} ${de ? (m.count === 1 ? 'Buchung' : 'Buchungen') : 'bookings'}` : (de ? 'keine Buchung' : 'no booking')}{m.category ? ` · ${m.category}` : ''}</div></td>
            <td><Money value={m.amount} currency={r.currency} /></td><td className="muted"><Money value={m.previous} currency={r.currency} /></td><td>{delta(m.amount, m.previous, true)}</td></tr>)}
        </DataTable>
        {r.merchants.length > 15 && <Button variant="ghost" className="no-print" onClick={() => setAllMerchants(v => !v)}>{allMerchants ? (de ? 'Weniger zeigen' : 'Show fewer') : (de ? `Alle ${r.merchants.length} zeigen` : `Show all ${r.merchants.length}`)}</Button>}
      </Panel>
    </>}</QueryState>
  </div>
}
