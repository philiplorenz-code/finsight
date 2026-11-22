import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Pencil, Plus, Trash2 } from 'lucide-react'
import { api, send } from '../lib/api'
import type { Account } from '../lib/types'
import { formatDate, useLocale } from '../lib/i18n'
import { label } from '../lib/labels'
import { AccountSelect } from '../components/account-select'
import { UpcomingList } from '../components/upcoming'
import { Badge, Button, DataTable, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

export type PlanStatus = 'ok' | 'warning' | 'over'
export type PlanItem = {
  id: string; name: string; category?: string | null; account_id?: string | null; account_name?: string | null
  amount: string; actual: string; from_pot: string; elsewhere: string; bookings: number; remaining: string; projected?: string | null
  status: PlanStatus; history: { month: string; actual: string; status?: PlanStatus | null }[]
}
export type PlanReport = { month: string; running: boolean; days_elapsed: number; days_in_month: number; items: PlanItem[]; totals: { amount: string; actual: string; remaining: string }; categories?: string[] }
type Orders = {
  transfers: { account_id: string; account: string; amount: string; day: number; months: string[]; last: string; active: boolean }[]
  transfers_monthly: string
  debits: { name: string; kind: string; period: string; monthly: string; annual: string; next_charge?: string | null; last_charge?: string | null; currency: string }[]
}

const TONE: Record<PlanStatus, string> = { ok: 'success', warning: 'warning', over: 'danger' }
export function StatusDot({ status, de }: { status?: PlanStatus | null; de: boolean }) {
  if (!status) return <span className="plan-dot none" aria-label={de ? 'laufend' : 'running'} />
  const label = { ok: de ? 'im Rahmen' : 'on track', warning: de ? 'knapp' : 'tight', over: de ? 'überschritten' : 'over' }[status]
  return <span className={`plan-dot ${status}`} role="img" aria-label={label} title={label} />
}

function shift(month: string, by: number) {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + by, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}

export default function PlanPage() {
  const { language } = useLocale(); const de = language === 'de'
  const [month, setMonth] = useState<string | null>(null)
  const [editing, setEditing] = useState<PlanItem | 'new' | null>(null)
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['plan', month], queryFn: () => api<PlanReport>(`/plan?history=6${month ? `&month=${month}` : ''}`) })
  const orders = useQuery({ queryKey: ['standing-orders'], queryFn: () => api<Orders>('/standing-orders') })
  const remove = useMutation({ mutationFn: (id: string) => send(`/plan-items/${encodeURIComponent(id)}`, undefined, 'DELETE'), onSuccess: () => client.invalidateQueries({ queryKey: ['plan'] }) })
  const data = query.data
  const current = data?.month
  return <>
    <PageHeader title={de ? 'Soll / Ist' : 'Plan vs. actual'} description={de ? 'Lege fest, wie viel pro Monat wofür vorgesehen ist, und vergleiche es mit deinen echten Ausgaben – aus dem Topf und von allen anderen Konten.' : 'Set what each purpose may cost per month and compare it with real spending — from the pot and from any other account.'}
      action={<Button onClick={() => setEditing('new')}><Plus size={17} />{de ? 'Posten anlegen' : 'Add item'}</Button>} />
    <Panel title={current ? new Intl.DateTimeFormat(de ? 'de-DE' : 'en-GB', { month: 'long', year: 'numeric' }).format(new Date(`${current}-01T00:00:00`)) : ''}
      description={data?.running ? (de ? `Laufender Monat: Tag ${data.days_elapsed} von ${data.days_in_month}. Die Hochrechnung schreibt den bisherigen Verbrauch bis Monatsende fort.` : `Running month: day ${data.days_elapsed} of ${data.days_in_month}. The projection extends spending so far to month end.`) : undefined}
      action={current && <div className="badge-row"><Button variant="outline" aria-label={de ? 'Vormonat' : 'Previous month'} onClick={() => setMonth(shift(current, -1))}><ChevronLeft size={16} /></Button><Button variant="outline" aria-label={de ? 'Folgemonat' : 'Next month'} disabled={data?.running} onClick={() => setMonth(shift(current, 1))}><ChevronRight size={16} /></Button></div>}>
      <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={false}>
        {data && !data.items.length && <p className="muted">{de ? 'Noch keine Posten. Lege z. B. „Tanken – 180 €“ mit Kategorie Tanken und deinem Tank-Topf an.' : 'No items yet. Add e.g. “Fuel – 180 €” with the fuel category and your fuel pot.'}</p>}
        {data && !!data.items.length && <DataTable variant="plan" headers={['', de ? 'Posten' : 'Item', de ? 'Soll' : 'Plan', de ? 'Ist' : 'Actual', de ? 'Rest' : 'Left', de ? 'Hochrechnung' : 'Projection', de ? 'Verlauf (6 Monate)' : 'History (6 months)', '']}>
          {data.items.map(i => <tr key={i.id}>
            <td><StatusDot status={i.status} de={de} /></td>
            <td><strong>{i.name}</strong><div className="small muted">{[i.category, i.account_name && `${de ? 'Topf' : 'Pot'}: ${i.account_name}`].filter(Boolean).join(' · ')}</div></td>
            <td className="nowrap"><Money value={i.amount} /></td>
            <td className="nowrap"><Money value={i.actual} /><div className="small muted">{de ? 'Topf' : 'Pot'} <Money value={i.from_pot} /> · {de ? 'andere Konten' : 'elsewhere'} <Money value={i.elsewhere} /></div></td>
            <td className="nowrap"><Money value={i.remaining} className={Number(i.remaining) < 0 ? 'negative' : ''} /></td>
            <td className="nowrap">{i.projected ? <Money value={i.projected} /> : '—'}</td>
            <td><div className="plan-trail">{i.history.map(h => <span key={h.month} className={`plan-cell ${h.status ?? 'none'}`} title={`${h.month}: ${Number(h.actual).toFixed(0)} €`}>{h.month.slice(5)}<b>{Number(h.actual).toFixed(0)}</b></span>)}</div></td>
            <td className="nowrap"><Button variant="ghost" aria-label={`${de ? 'Bearbeiten' : 'Edit'}: ${i.name}`} onClick={() => setEditing(i)}><Pencil size={16} /></Button><Button variant="ghost" aria-label={`${de ? 'Löschen' : 'Delete'}: ${i.name}`} onClick={() => remove.mutate(i.id)}><Trash2 size={16} /></Button></td>
          </tr>)}
          <tr><td /><td><strong>{de ? 'Summe' : 'Total'}</strong></td><td><Money value={data.totals.amount} /></td><td><Money value={data.totals.actual} /></td><td><Money value={data.totals.remaining} /></td><td colSpan={3} /></tr>
        </DataTable>}
        <Feedback error={remove.error} />
      </QueryState>
    </Panel>
    <UpcomingList days={30} />
    <Panel title={de ? 'Daueraufträge in deine Töpfe' : 'Standing orders into your pots'} description={de ? 'Erkannt aus gleich hohen Umbuchungen in mindestens zwei der letzten drei Monate.' : 'Detected from equal transfers in at least two of the last three months.'}>
      <QueryState pending={orders.isPending} error={orders.error} retry={orders.refetch} empty={!orders.data?.transfers.length}>
        <DataTable headers={[de ? 'Ziel' : 'Target', de ? 'Betrag' : 'Amount', de ? 'Tag' : 'Day', de ? 'Monate' : 'Months', de ? 'Status' : 'Status']}>
          {orders.data?.transfers.map(o => <tr key={`${o.account_id}-${o.amount}`}><td>{o.account}</td><td><Money value={o.amount} /></td><td>{o.day}.</td><td className="small muted">{o.months.join(', ')}</td><td><Badge tone={o.active ? 'success' : ''}>{o.active ? (de ? 'läuft' : 'active') : (de ? 'pausiert?' : 'paused?')}</Badge></td></tr>)}
          <tr><td><strong>{de ? 'Summe laufend' : 'Active total'}</strong></td><td><Money value={orders.data?.transfers_monthly} /></td><td colSpan={3} /></tr>
        </DataTable>
      </QueryState>
    </Panel>
    <Panel title={de ? 'Lastschriften, Abos und Verträge' : 'Direct debits, subscriptions and contracts'} description={de ? 'Laufende wiederkehrende Abbuchungen (Schätzung aus Buchungen).' : 'Running recurring debits (estimated from bookings).'}>
      <QueryState pending={orders.isPending} error={orders.error} retry={orders.refetch} empty={!orders.data?.debits.length}>
        <DataTable headers={[de ? 'Name' : 'Name', de ? 'Rhythmus' : 'Rhythm', de ? 'pro Monat' : 'per month', de ? 'pro Jahr' : 'per year', de ? 'Nächste' : 'Next']}>
          {orders.data?.debits.slice().sort((a, b) => Number(b.monthly) - Number(a.monthly)).map((d, i) => <tr key={`${d.name}-${i}`}><td>{d.name}</td><td className="small">{label('period', d.period, language)}</td><td><Money value={d.monthly} currency={d.currency} /></td><td><Money value={d.annual} currency={d.currency} /></td><td className="small muted">{d.next_charge ? formatDate(d.next_charge, language) : '—'}</td></tr>)}
        </DataTable>
      </QueryState>
    </Panel>
    {editing && <PlanForm item={editing === 'new' ? null : editing} categories={data?.categories ?? []} onClose={() => setEditing(null)} />}
  </>
}

function PlanForm({ item, categories, onClose }: { item: PlanItem | null; categories: string[]; onClose: () => void }) {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts') })
  const [form, setForm] = useState({ name: item?.name ?? '', amount: item ? String(Number(item.amount)) : '', category: item?.category ?? '', account_id: item?.account_id ?? '' })
  const mutation = useMutation({
    mutationFn: () => {
      const body = { name: form.name, amount: form.amount, category: form.category || null, account_id: form.account_id || null }
      return item ? send(`/plan-items/${encodeURIComponent(item.id)}`, body, 'PATCH') : send('/plan-items', body)
    },
    onSuccess: () => { client.invalidateQueries({ queryKey: ['plan'] }); onClose() },
  })
  const owned = (accounts.data ?? []).filter(a => a.ownership === 'owned' && a.included !== false)
  return <Dialog title={item ? (de ? 'Posten bearbeiten' : 'Edit item') : (de ? 'Posten anlegen' : 'Add item')} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
      <div className="form-grid">
        <Field label={de ? 'Name' : 'Name'}><input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label={de ? 'Soll pro Monat (€)' : 'Plan per month (€)'}><input required type="number" min="0" step="0.01" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></Field>
      </div>
      <Field label={de ? 'Kategorie (Buchungen von allen Konten)' : 'Category (bookings on any account)'} hint={de ? 'Leer lassen, wenn nur der Topf zählen soll.' : 'Leave empty to count only the pot.'}>
        <input list="plan-categories" maxLength={100} value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} />
        <datalist id="plan-categories">{categories.map(c => <option key={c} value={c} />)}</datalist>
      </Field>
      <AccountSelect accounts={owned} value={form.account_id} onChange={id => setForm({ ...form, account_id: id })} anyLabel={de ? 'Kein Topf' : 'No pot'} label={de ? 'Topf (alle Abgänge zählen)' : 'Pot (all outflows count)'} />
      {!form.category && !form.account_id && <Notice warning>{de ? 'Wähle eine Kategorie, einen Topf oder beides.' : 'Choose a category, a pot or both.'}</Notice>}
      <Feedback error={mutation.error} />
      <Button busy={mutation.isPending} disabled={!form.category && !form.account_id}>{de ? 'Speichern' : 'Save'}</Button>
    </form>
  </Dialog>
}
