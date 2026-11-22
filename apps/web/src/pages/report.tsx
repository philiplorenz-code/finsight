import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Printer } from 'lucide-react'
import { api } from '../lib/api'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'
import { Button, DataTable, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'
import { StatusDot, type PlanStatus } from './plan'

type Cat = { category: string; amount: string; previous: string; average: string; change: string }
type Report = {
  month: string; currency: string; complete: boolean; income: string; expenses: string; surplus: string; savings_rate?: string | null
  previous: { income: string; expenses: string; surplus: string }; average_6m: { income: string; expenses: string; surplus: string }
  money_end: string; money_change: string; categories: Cat[]
  biggest: { id: string; date: string; merchant: string; category?: string; account: string; amount: string }[]
  plan: { name: string; amount: string; actual: string; status: PlanStatus }[]
  anomalies: { key: string; kind: string; merchant?: string; amount: string; date: string }[]
  highlights: { kind: string; amount?: string; category?: string; count?: number }[]
}

function shift(month: string, by: number) {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + by, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}

export default function ReportPage() {
  const { language } = useLocale(); const de = language === 'de'
  const [month, setMonth] = useState<string | null>(null)
  const query = useQuery({ queryKey: ['report', month], queryFn: () => api<Report>(`/reports/monthly${month ? `?month=${month}` : ''}`) })
  const r = query.data
  const money = (v?: string | number | null) => formatMoney(String(v ?? 0), r?.currency ?? 'EUR', language)
  const delta = (now: string, before: string, inverse = false) => {
    const d = Number(now) - Number(before)
    if (Math.abs(d) < 0.5) return <small className="muted">±0</small>
    const good = inverse ? d < 0 : d > 0
    return <small className={good ? 'positive' : 'negative'}>{d > 0 ? '+' : ''}{money(d)}</small>
  }
  const title = r ? new Intl.DateTimeFormat(de ? 'de-DE' : 'en-GB', { month: 'long', year: 'numeric' }).format(new Date(`${r.month}-01T00:00:00`)) : ''
  const highlight = (h: Report['highlights'][number]) => ({
    spending_high: de ? `Du hast ${money(h.amount)} mehr ausgegeben als im Schnitt der letzten 6 Monate.` : `You spent ${money(h.amount)} more than the 6-month average.`,
    spending_low: de ? `Du hast ${money(h.amount)} weniger ausgegeben als im Schnitt – gut gemacht.` : `You spent ${money(h.amount)} less than average – well done.`,
    category_up: de ? `${h.category} lag ${money(h.amount)} über deinem Durchschnitt.` : `${h.category} was ${money(h.amount)} above your average.`,
    plan_over: de ? `${h.count} Soll-Posten wurden überschritten.` : `${h.count} plan items went over.`,
  } as Record<string, string>)[h.kind] ?? h.kind
  return <div className="report-page">
    <PageHeader title={de ? `Monatsabschluss${title ? ` ${title}` : ''}` : `Monthly close${title ? ` ${title}` : ''}`} description={de ? 'Dein Monat auf einer Seite – im Vergleich zum Vormonat und zum Durchschnitt der letzten sechs Monate.' : 'Your month on one page – compared with last month and the six-month average.'}
      action={r && <div className="badge-row no-print">
        <Button variant="outline" aria-label={de ? 'Vormonat' : 'Previous month'} onClick={() => setMonth(shift(r.month, -1))}><ChevronLeft size={16} /></Button>
        <Button variant="outline" aria-label={de ? 'Folgemonat' : 'Next month'} onClick={() => setMonth(shift(r.month, 1))}><ChevronRight size={16} /></Button>
        <Button variant="outline" onClick={() => window.print()}><Printer size={16} />{de ? 'Drucken / PDF' : 'Print / PDF'}</Button>
      </div>} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{r && <>
      {!r.complete && <Notice>{de ? 'Der Monat läuft noch – die Zahlen sind vorläufig.' : 'This month is still running – figures are provisional.'}</Notice>}
      <div className="stat-grid">
        <div className="detail-stat"><span>{de ? 'Einnahmen' : 'Income'}</span><strong>{money(r.income)}</strong>{delta(r.income, r.previous.income)}</div>
        <div className="detail-stat"><span>{de ? 'Ausgaben' : 'Expenses'}</span><strong>{money(r.expenses)}</strong>{delta(r.expenses, r.previous.expenses, true)}</div>
        <div className="detail-stat"><span>{de ? 'Überschuss' : 'Surplus'}</span><strong>{money(r.surplus)}</strong>{delta(r.surplus, r.previous.surplus)}</div>
        <div className="detail-stat"><span>{de ? 'Sparquote' : 'Savings rate'}</span><strong>{r.savings_rate != null ? `${Math.round(Number(r.savings_rate) * 100)} %` : '—'}</strong></div>
        <div className="detail-stat"><span>{de ? 'Dein Geld am Monatsende' : 'Your money at month end'}</span><strong>{money(r.money_end)}</strong>{delta(r.money_change, '0')}</div>
      </div>
      <small className="muted">{de ? 'Vergleich zum Vormonat. Ø 6 Monate' : 'Change vs. last month. 6-month avg'}: {de ? 'Einnahmen' : 'income'} {money(r.average_6m.income)} · {de ? 'Ausgaben' : 'expenses'} {money(r.average_6m.expenses)}</small>
      {!!r.highlights.length && <Panel title={de ? 'Das Wichtigste' : 'Highlights'}><ul className="report-highlights">{r.highlights.map((h, i) => <li key={i}>{highlight(h)}</li>)}</ul></Panel>}
      <Panel title={de ? 'Ausgaben nach Kategorie' : 'Spending by category'}>
        <DataTable headers={[de ? 'Kategorie' : 'Category', de ? 'Dieser Monat' : 'This month', de ? 'Vormonat' : 'Last month', 'Ø 6 M.', de ? 'vs. Ø' : 'vs. avg']}>
          {r.categories.map(c => <tr key={c.category}><td>{c.category}</td><td><Money value={c.amount} currency={r.currency} /></td><td className="muted"><Money value={c.previous} currency={r.currency} /></td><td className="muted"><Money value={c.average} currency={r.currency} /></td><td>{delta(c.amount, c.average, true)}</td></tr>)}
        </DataTable>
      </Panel>
      <div className="report-grid">
        <Panel title={de ? 'Größte Ausgaben' : 'Biggest expenses'}>
          <DataTable headers={[de ? 'Datum' : 'Date', de ? 'Empfänger' : 'Payee', de ? 'Konto' : 'Account', de ? 'Betrag' : 'Amount']}>
            {r.biggest.map(b => <tr key={b.id}><td className="nowrap small">{formatDate(b.date, language)}</td><td>{b.merchant}<div className="small muted">{b.category}</div></td><td className="small muted">{b.account}</td><td className="nowrap"><Money value={b.amount} currency={r.currency} /></td></tr>)}
          </DataTable>
        </Panel>
        <Panel title={de ? 'Soll / Ist' : 'Plan vs. actual'}>
          {!r.plan.length ? <p className="muted">{de ? 'Keine Soll-Posten angelegt.' : 'No plan items yet.'}</p> :
            <ul className="plan-list">{r.plan.map(p => <li key={p.name}><StatusDot status={p.status} de={de} /><span>{p.name}</span><span className="small muted"><Money value={p.actual} /> / <Money value={p.amount} /></span></li>)}</ul>}
          {!!r.anomalies.length && <><h3>{de ? 'Auffälligkeiten' : 'Anomalies'}</h3><ul className="report-highlights">{r.anomalies.map(a => <li key={a.key}>{formatDate(a.date, language)} · {a.merchant} · {money(a.amount)}</li>)}</ul></>}
        </Panel>
      </div>
    </>}</QueryState>
  </div>
}
