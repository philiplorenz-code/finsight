import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, items, send } from '../lib/api'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'
import { DataTable, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Source = { account_id: string; name: string; amount: string; count: number; months?: number }
type Month = { month: string; budget: string; topups: string; topup_count: number; spending: string; refunds: string; moved_out: string; gap: string; first_topup: string | null; end_balance: string | null; sources: Source[] }
type Watch = {
  account: { id: string; name: string; provider?: string | null } | null
  watched: string | null
  months?: Month[]
  budget_sources?: { account_id: string; name: string; day: number; amount: string }[]
  budget_source_override?: string | null
  candidates?: { account_id: string; name: string }[]
  summary?: { full_months: number; running_month: string; budget: string; topups: string; topup_count: number; months_with_topups: number; spending: string; covered_by_topups: string | null; biggest_month: string | null }
  sources?: Source[]
  categories?: { name: string; amount: string }[]
  balance_observed?: string | null
}
type Account = { id: string; name: string; ownership: string; inactive: boolean; provider?: string | null }

export default function WatchPage() {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const [accountId, setAccountId] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[] | { items?: Account[] }>('/accounts') })
  const query = useQuery({ queryKey: ['watch', accountId], queryFn: () => api<Watch>(`/watch${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''}`) })
  const save = useMutation({
    mutationFn: (body: { account_id: string; auto_budget: boolean; budget_source?: string | null }) => send('/watch', body, 'PUT'),
    onSuccess: () => { setAccountId(null); client.invalidateQueries({ queryKey: ['watch'] }) },
  })
  const w = query.data
  const money = (v?: string | number | null) => formatMoney(String(v ?? 0), 'EUR', language)
  const monthName = (m: string, style: 'long' | 'short' = 'long') => new Intl.DateTimeFormat(de ? 'de-DE' : 'en-GB', { month: style, ...(style === 'long' ? { year: 'numeric' } : {}) }).format(new Date(`${m}-01T00:00:00`))
  const owned = items(accounts.data).filter(a => a.ownership === 'owned' && !a.inactive).sort((a, b) => a.name.localeCompare(b.name))
  const budgetMode = w?.budget_source_override == null ? 'auto' : w.budget_source_override === '' ? 'none' : w.budget_source_override
  const chart = (w?.months ?? []).map(m => ({ name: monthName(m.month, 'short'), budget: Number(m.budget), topups: Number(m.topups), spending: Number(m.spending) - Number(m.refunds) }))
  const s = w?.summary
  const full = (w?.months ?? []).filter(m => m.month !== s?.running_month)
  const needs = full.map(m => Number(m.spending) - Number(m.refunds))
  const movedOut = full.reduce((sum, m) => sum + Number(m.moved_out), 0)
  return <div className="report-page">
    <PageHeader title={de ? `Konto im Blick${w?.account ? `: ${w.account.name}` : ''}` : `Account watch${w?.account ? `: ${w.account.name}` : ''}`}
      description={de ? 'Wie viel Budget kommt regelmäßig, wie oft musst du nachschießen und von welchen Konten.' : 'How much regular budget arrives, how often you top up and from which accounts.'} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{w && <>
      <Panel>
        <div className="form-grid">
          <Field label={de ? 'Beobachtetes Konto' : 'Watched account'}>
            <select value={w.account?.id ?? ''} onChange={e => { setAccountId(e.target.value); save.mutate({ account_id: e.target.value, auto_budget: true }) }}>
              {!w.account && <option value="">—</option>}
              {owned.map(a => <option key={a.id} value={a.id}>{a.name}{a.provider ? ` (${a.provider})` : ''}</option>)}
            </select>
          </Field>
          {w.account && <Field label={de ? 'Was zählt als Budget?' : 'What counts as budget?'} hint={de ? 'Automatisch: eine Umbuchung pro Monat vom selben Konto, am selben Tag, in ähnlicher Höhe.' : 'Automatic: one transfer per month from the same account, same day, similar amount.'}>
            <select value={budgetMode} onChange={e => {
              const v = e.target.value
              save.mutate(v === 'auto' ? { account_id: w.account!.id, auto_budget: true } : { account_id: w.account!.id, auto_budget: false, budget_source: v === 'none' ? null : v })
            }}>
              <option value="auto">{de ? 'Automatisch erkennen' : 'Detect automatically'}</option>
              <option value="none">{de ? 'Kein Budget, alles ist Nachschuss' : 'No budget, everything is a top-up'}</option>
              {(w.candidates ?? []).map(c => <option key={c.account_id} value={c.account_id}>{de ? `Monatliche Zahlung von ${c.name}` : `Monthly payment from ${c.name}`}</option>)}
            </select>
          </Field>}
        </div>
        <Feedback error={save.error} />
      </Panel>
      {!w.account && <Notice>{de ? 'Wähle oben das Konto, das du beobachten willst.' : 'Pick the account to watch above.'}</Notice>}
      {w.account && s && <>
        <Notice>{w.budget_sources?.length
          ? (de ? `Als Budget erkannt: ${w.budget_sources.map(b => `${money(b.amount)} von ${b.name} um den ${b.day}.`).join(', ')}. Alles andere, was von deinen Konten kommt, zählt als Nachschuss.`
            : `Detected budget: ${w.budget_sources.map(b => `${money(b.amount)} from ${b.name} around day ${b.day}`).join(', ')}. Everything else from your accounts is a top-up.`)
          : (de ? 'Kein regelmäßiges Budget erkannt. Jede Umbuchung von deinen Konten zählt als Nachschuss.' : 'No regular budget found. Every transfer from your accounts counts as a top-up.')}</Notice>
        <div className="stat-grid">
          <div className="detail-stat"><span>{de ? `Budget (${s.full_months} Monate)` : `Budget (${s.full_months} months)`}</span><strong>{money(s.budget)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Nachgeschossen' : 'Topped up'}</span><strong className="negative">{money(s.topups)}</strong><small className="muted">{s.topup_count} {de ? 'Umbuchungen' : 'transfers'}</small></div>
          <div className="detail-stat"><span>{de ? 'Ausgegeben' : 'Spent'}</span><strong>{money(s.spending)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Monate mit Nachschuss' : 'Months with top-ups'}</span><strong>{s.months_with_topups} / {s.full_months}</strong>{s.covered_by_topups != null && <small className="muted">{de ? `${Math.round(Number(s.covered_by_topups) * 100)} % der Ausgaben` : `${Math.round(Number(s.covered_by_topups) * 100)} % of spending`}</small>}</div>
        </div>
        {!!needs.length && <small className="muted">{de
          ? `Tatsächlich gebraucht pro Monat: zwischen ${money(Math.min(...needs))} und ${money(Math.max(...needs))}. Budget zuletzt: ${money(full[full.length - 1]?.budget)}.${movedOut > 0 ? ` Im selben Zeitraum gingen ${money(movedOut)} wieder auf andere Konten (z. B. Aufrundungen).` : ''}`
          : `Actually needed per month: between ${money(Math.min(...needs))} and ${money(Math.max(...needs))}.${movedOut > 0 ? ` ${money(movedOut)} went back out to other accounts (e.g. round-ups).` : ''}`}</small>}
        <Panel title={de ? 'Budget, Nachschuss und Ausgaben pro Monat' : 'Budget, top-ups and spending per month'}>
          <div className="chart-container" role="img" aria-label={de ? 'Budget, Nachschuss und Ausgaben pro Monat' : 'Budget, top-ups and spending per month'}><ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chart}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" /><YAxis width={56} tickFormatter={v => `${Math.round(Number(v) / 100) / 10}k`} />
              <Tooltip formatter={v => money(Number(v))} /><Legend />
              <Bar isAnimationActive={false} stackId="in" name="Budget" dataKey="budget" fill="#287a68" />
              <Bar isAnimationActive={false} stackId="in" name={de ? 'Nachschuss' : 'Top-ups'} dataKey="topups" fill="#d08a3c" />
              <Line isAnimationActive={false} type="monotone" name={de ? 'Ausgaben' : 'Spending'} dataKey="spending" stroke="#5b6b67" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart></ResponsiveContainer></div>
          <DataTable headers={[de ? 'Monat' : 'Month', 'Budget', de ? 'Nachschuss' : 'Top-ups', de ? 'Ausgaben' : 'Spending', de ? 'Stand Monatsende' : 'Month-end balance']}>
            {(w.months ?? []).slice().reverse().map(m => <Fragment key={m.month}>
              <tr>
                <td>{m.topup_count ? <button className="text-link" aria-expanded={open === m.month} onClick={() => setOpen(open === m.month ? null : m.month)}>{monthName(m.month)}</button> : monthName(m.month)}
                  {m.month === s.running_month && <div className="small muted">{de ? 'läuft noch' : 'running'}</div>}
                  {m.first_topup && <div className="small muted">{de ? `erster Nachschuss am ${formatDate(m.first_topup, language)}` : `first top-up ${formatDate(m.first_topup, language)}`}</div>}</td>
                <td><Money value={m.budget} /></td>
                <td className={Number(m.topups) > 0 ? 'negative' : ''}><Money value={m.topups} />{m.topup_count > 0 && <div className="small muted">{m.topup_count}×</div>}</td>
                <td><Money value={String(Number(m.spending) - Number(m.refunds))} /></td>
                <td>{m.end_balance == null ? '—' : <Money value={m.end_balance} />}</td>
              </tr>
              {open === m.month && <tr><td colSpan={5}><ul className="report-highlights">
                {m.sources.map(src => <li key={src.account_id}>{src.name}: <strong>{money(src.amount)}</strong> ({src.count}×)</li>)}
              </ul></td></tr>}
            </Fragment>)}
          </DataTable>
          {w.balance_observed && <small className="muted">{de ? `Stand Monatsende ist aus dem Kontostand vom ${formatDate(w.balance_observed, language)} zurückgerechnet.` : `Month-end balance is calculated back from the balance on ${formatDate(w.balance_observed, language)}.`}</small>}
        </Panel>
        <Panel title={de ? 'Woher der Nachschuss kommt' : 'Where the top-ups come from'}>
          <DataTable headers={[de ? 'Konto' : 'Account', de ? 'Summe' : 'Total', de ? 'Umbuchungen' : 'Transfers', de ? 'Monate' : 'Months']}>
            {(w.sources ?? []).map(src => <tr key={src.account_id}><td>{src.name}</td><td><Money value={src.amount} /></td><td>{src.count}</td><td>{src.months} / {s.full_months + 1}</td></tr>)}
          </DataTable>
        </Panel>
        <Panel title={de ? `Wofür das Geld auf ${w.account.name} draufgeht` : `What ${w.account.name} is spent on`}>
          <DataTable headers={[de ? 'Kategorie' : 'Category', de ? 'Summe' : 'Total']}>
            {(w.categories ?? []).map(c => <tr key={c.name}><td>{c.name}</td><td><Money value={c.amount} /></td></tr>)}
          </DataTable>
          <Link className="text-link" to={`/transactions?account_id=${w.account.id}`}>{de ? 'Alle Buchungen ansehen' : 'See all bookings'}</Link>
        </Panel>
      </>}
    </>}</QueryState>
  </div>
}
