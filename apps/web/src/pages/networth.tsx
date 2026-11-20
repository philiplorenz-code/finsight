import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { localizeWarning } from '../lib/warnings'
import { Badge, Button, Dialog, Feedback, Field, Money, PageHeader, Panel, QueryState } from '../components/ui'

type AccountRow = { id: string; name: string; purpose: string; balance: string; observed_date: string; share: string; mine: string; others: string }
type Holding = { id: string; name: string; kind: 'asset' | 'liability'; category: string; value: string; share: string; mine: string; others: string; monthly_payment: string | null; interest_rate: string | null; note: string; months_left?: number | null; payoff_date?: string | null; schedule?: { month: string; balance: string }[] }
type NetWorth = {
  currency: string; accounts: AccountRow[]; holdings: Holding[]; accounts_without_balance: number; stale_balances: number
  totals: Record<'assets_mine' | 'assets_others' | 'liabilities_mine' | 'liabilities_others' | 'net_worth_mine' | 'net_worth_others' | 'net_worth_gross' | 'monthly_debt_service', string>
  history: { month: string; accounts_mine: string; holdings_mine?: string; holdings_counted?: number; net_worth_mine?: string }[]
}
const CATEGORIES = ['car', 'property', 'loan', 'depot', 'cash', 'other'] as const

export default function NetWorthPage() {
  const { language } = useLocale()
  const de = language === 'de'
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['net-worth'], queryFn: () => api<NetWorth>('/net-worth') })
  const [editing, setEditing] = useState<Holding | 'new' | null>(null)
  const refresh = () => { client.invalidateQueries({ queryKey: ['net-worth'] }); client.invalidateQueries({ queryKey: ['accounts'] }) }
  const share = useMutation({ mutationFn: ({ id, value }: { id: string; value: number }) => send(`/accounts/${id}`, { owner_share: value }, 'PATCH'), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: string) => send(`/holdings/${id}`, undefined, 'DELETE'), onSuccess: refresh })
  const data = query.data
  const tt = data?.totals
  const cat = (c: string) => de ? ({ car: 'Auto', property: 'Immobilie', loan: 'Kredit', depot: 'Depot', cash: 'Bargeld', other: 'Sonstiges' } as Record<string, string>)[c] ?? c : c
  const assets = data?.holdings.filter(h => h.kind === 'asset') ?? []
  const debts = data?.holdings.filter(h => h.kind === 'liability') ?? []
  const history = data?.history.map(h => ({ month: h.month, accounts: Number(h.accounts_mine), total: Number(h.net_worth_mine ?? h.accounts_mine) })) ?? []
  const [debtId, setDebtId] = useState('')
  const schedDebt = debts.find(d => d.id === debtId) ?? debts.find(d => d.schedule?.length)
  const cur = data?.currency ?? 'EUR'
  return <>
    <PageHeader title={de ? 'Vermögen' : 'Net worth'} description={de ? 'Alles, was du besitzt und schuldest – getrennt nach dem Anteil, der dir gehört, und dem, der jemand anderem gehört.' : 'Everything you own and owe, split into your share and what belongs to someone else.'} action={<Button onClick={() => setEditing('new')}><Plus size={16} />{de ? 'Eintrag hinzufügen' : 'Add entry'}</Button>} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>
      {data && tt && <>
        <div className="stat-grid">
          <div className="detail-stat"><span>{de ? 'Mein Netto-Vermögen' : 'My net worth'}</span><Money value={tt.net_worth_mine} currency={cur} /></div>
          <div className="detail-stat"><span>{de ? 'Mein Vermögen' : 'My assets'}</span><Money value={tt.assets_mine} currency={cur} /></div>
          <div className="detail-stat"><span>{de ? 'Meine Schulden' : 'My debts'}</span><Money value={tt.liabilities_mine} currency={cur} /></div>
          <div className="detail-stat"><span>{de ? 'Gehört anderen (netto)' : 'Belongs to others (net)'}</span><Money value={tt.net_worth_others} currency={cur} /></div>
          <div className="detail-stat"><span>{de ? 'Raten pro Monat (mein Anteil)' : 'Payments per month (my share)'}</span><Money value={tt.monthly_debt_service} currency={cur} /></div>
        </div>
        {(data.accounts_without_balance > 0 || data.stale_balances > 0) && <p className="muted">{de
          ? `Datengrundlage: ${data.accounts_without_balance} Konten ohne Kontostand, ${data.stale_balances} mit Kontostand älter als 7 Tage. Ein frischer Export aktualisiert das.`
          : `${data.accounts_without_balance} accounts without balance, ${data.stale_balances} with a balance older than 7 days.`}</p>}
        {history.length > 1 && <Panel title={de ? 'Verlauf des Vermögens (mein Anteil)' : 'Net worth over time (my share)'} description={de ? 'Sachwerte und Schulden zählen ab ihrer ersten Bewertung; jede Wertänderung wird festgehalten.' : 'Holdings count from their first valuation; every value change is recorded.'}>
          <div className="chart-container" role="img" aria-label="net worth history"><ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
              <YAxis axisLine={false} tickLine={false} width={64} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickFormatter={v => formatMoney(String(v), cur, language)} />
              <Tooltip contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12 }} formatter={(v) => formatMoney(String(v), cur, language)} />
              <Area dataKey="total" name={de ? 'Vermögen gesamt' : 'Net worth'} stroke="#287a68" fill="#287a68" fillOpacity={0.18} />
              <Area dataKey="accounts" name={de ? 'Nur Kontostände' : 'Accounts only'} stroke="#6b7fd7" fill="none" strokeDasharray="4 3" />
            </AreaChart>
          </ResponsiveContainer></div>
        </Panel>}
        {schedDebt?.schedule?.length ? <Panel title={de ? 'Tilgungsplan' : 'Repayment schedule'} description={de ? 'Restschuld pro Monat bei gleichbleibender Rate und Zins (Zinsen monatlich = Zinssatz/12).' : 'Remaining debt per month at a fixed payment and rate (monthly interest = rate/12).'}>
          {debts.filter(d => d.schedule?.length).length > 1 && <select aria-label={de ? 'Schuld wählen' : 'Choose debt'} value={schedDebt.id} onChange={e => setDebtId(e.target.value)}>{debts.filter(d => d.schedule?.length).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>}
          <div className="chart-container" role="img" aria-label="repayment schedule"><ResponsiveContainer width="100%" height="100%">
            <AreaChart data={schedDebt.schedule.map(r => ({ month: r.month, value: Number(r.balance) }))} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} minTickGap={40} />
              <YAxis axisLine={false} tickLine={false} width={64} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickFormatter={v => formatMoney(String(v), cur, language)} />
              <Tooltip contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12 }} formatter={(v) => formatMoney(String(v), cur, language)} />
              <Area dataKey="value" name={de ? 'Restschuld' : 'Remaining'} stroke="#b4503c" fill="#b4503c" fillOpacity={0.16} />
            </AreaChart>
          </ResponsiveContainer></div>
        </Panel> : null}
        <AsOfPanel de={de} cur={cur} />
        <Panel title={de ? 'Konten' : 'Accounts'} description={de ? 'Anteil: wie viel Prozent des Kontostands dir gehören (Gemeinschaftskonto, Konto von Partner/Firma …).' : 'Share: percentage of the balance that is yours.'}>
          <table className="data-table"><thead><tr><th>{de ? 'Konto' : 'Account'}</th><th>{de ? 'Kontostand' : 'Balance'}</th><th>{de ? 'Mein Anteil %' : 'My share %'}</th><th>{de ? 'Mir' : 'Mine'}</th><th>{de ? 'Anderen' : 'Others'}</th></tr></thead>
            <tbody>{data.accounts.map(a => <tr key={a.id}><td>{a.name}</td><td><Money value={a.balance} currency={cur} /></td>
              <td><input aria-label={`${a.name}: ${de ? 'Anteil' : 'share'}`} type="number" min={0} max={100} step="1" defaultValue={Number(a.share)} style={{ width: 80 }}
                onBlur={e => { const v = Number(e.target.value); if (!Number.isNaN(v) && v !== Number(a.share) && v >= 0 && v <= 100) share.mutate({ id: a.id, value: v }) }} /></td>
              <td><Money value={a.mine} currency={cur} /></td><td><Money value={a.others} currency={cur} /></td></tr>)}</tbody></table>
          <Feedback error={share.error} />
        </Panel>
        <Panel title={de ? 'Sachwerte und Vermögen' : 'Assets'}>
          <HoldingTable rows={assets} cur={cur} de={de} cat={cat} onEdit={setEditing} onDelete={id => remove.mutate(id)} />
        </Panel>
        <Panel title={de ? 'Schulden und Kredite' : 'Debts and loans'} description={de ? 'Restschuld, Rate und – bei gesetzter Rate – wann alles abbezahlt ist.' : 'Remaining debt, payment and payoff date.'}>
          <HoldingTable rows={debts} cur={cur} de={de} cat={cat} debt onEdit={setEditing} onDelete={id => remove.mutate(id)} />
        </Panel>
      </>}
    </QueryState>
    {editing && <HoldingDialog holding={editing === 'new' ? null : editing} de={de} cat={cat} onClose={() => setEditing(null)} onDone={() => { setEditing(null); refresh() }} />}
  </>
}

function HoldingTable({ rows, cur, de, cat, debt, onEdit, onDelete }: { rows: Holding[]; cur: string; de: boolean; cat: (c: string) => string; debt?: boolean; onEdit: (h: Holding) => void; onDelete: (id: string) => void }) {
  if (!rows.length) return <p className="muted">{de ? 'Noch keine Einträge.' : 'No entries yet.'}</p>
  return <table className="data-table"><thead><tr><th>{de ? 'Name' : 'Name'}</th><th>{de ? 'Wert' : 'Value'}</th><th>{de ? 'Anteil' : 'Share'}</th><th>{de ? 'Mir' : 'Mine'}</th><th>{de ? 'Anderen' : 'Others'}</th>{debt && <th>{de ? 'Rate / Monat' : 'Payment'}</th>}{debt && <th>{de ? 'Abbezahlt' : 'Paid off'}</th>}<th /></tr></thead>
    <tbody>{rows.map(h => <tr key={h.id}><td>{h.name} <Badge>{cat(h.category)}</Badge></td><td><Money value={h.value} currency={cur} /></td><td>{Number(h.share)} %</td><td><Money value={h.mine} currency={cur} /></td><td><Money value={h.others} currency={cur} /></td>
      {debt && <td>{h.monthly_payment ? <Money value={h.monthly_payment} currency={cur} /> : '—'}</td>}
      {debt && <td>{h.months_left == null ? (de ? 'unbekannt' : 'unknown') : h.months_left === 0 ? '✓' : `${h.payoff_date?.slice(0, 7)} (${h.months_left} ${de ? 'Mon.' : 'mo.'})`}</td>}
      <td className="nowrap"><Button variant="ghost" aria-label={`${de ? 'Bearbeiten' : 'Edit'}: ${h.name}`} onClick={() => onEdit(h)}><Pencil size={15} /></Button><Button variant="ghost" aria-label={`${de ? 'Löschen' : 'Delete'}: ${h.name}`} onClick={() => onDelete(h.id)}><Trash2 size={15} /></Button></td></tr>)}</tbody></table>
}

function HoldingDialog({ holding, de, cat, onClose, onDone }: { holding: Holding | null; de: boolean; cat: (c: string) => string; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({
    name: holding?.name ?? '', kind: holding?.kind ?? 'asset', category: holding?.category ?? 'other', value: holding ? String(Number(holding.value)) : '',
    share: holding ? String(Number(holding.share)) : '100', monthly_payment: holding?.monthly_payment ? String(Number(holding.monthly_payment)) : '',
    interest_rate: holding?.interest_rate ? String(Number(holding.interest_rate)) : '', note: holding?.note ?? '',
  })
  const set = (k: string, v: string) => setForm({ ...form, [k]: v })
  const save = useMutation({
    mutationFn: () => send(holding ? `/holdings/${holding.id}` : '/holdings', {
      name: form.name, kind: form.kind, category: form.category, value: form.value, share: form.share,
      monthly_payment: form.monthly_payment || null, interest_rate: form.interest_rate || null, note: form.note,
    }, holding ? 'PATCH' : 'POST'),
    onSuccess: onDone,
  })
  return <Dialog title={holding ? (de ? 'Eintrag bearbeiten' : 'Edit entry') : (de ? 'Eintrag hinzufügen' : 'Add entry')} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate() }}>
      <Field label={de ? 'Name' : 'Name'}><input required maxLength={300} value={form.name} onChange={e => set('name', e.target.value)} placeholder={de ? 'z. B. Auto, Autokredit' : 'e.g. car, car loan'} /></Field>
      <div className="form-grid">
        <Field label={de ? 'Art' : 'Kind'}><select value={form.kind} onChange={e => set('kind', e.target.value)}><option value="asset">{de ? 'Vermögen / Sachwert' : 'Asset'}</option><option value="liability">{de ? 'Schuld / Kredit' : 'Debt'}</option></select></Field>
        <Field label={de ? 'Kategorie' : 'Category'}><select value={form.category} onChange={e => set('category', e.target.value)}>{CATEGORIES.map(c => <option key={c} value={c}>{cat(c)}</option>)}</select></Field>
        <Field label={form.kind === 'liability' ? (de ? 'Restschuld (€)' : 'Remaining debt') : (de ? 'Aktueller Wert (€)' : 'Current value')}><input required type="number" min={0} step="0.01" value={form.value} onChange={e => set('value', e.target.value)} /></Field>
        <Field label={de ? 'Mein Anteil %' : 'My share %'} hint={de ? '100 = gehört ganz dir; 50 = halb jemand anderem' : '100 = all yours'}><input required type="number" min={0} max={100} step="1" value={form.share} onChange={e => set('share', e.target.value)} /></Field>
        {form.kind === 'liability' && <>
          <Field label={de ? 'Rate pro Monat (€)' : 'Monthly payment'}><input type="number" min={0} step="0.01" value={form.monthly_payment} onChange={e => set('monthly_payment', e.target.value)} /></Field>
          <Field label={de ? 'Zinssatz % p. a.' : 'Interest % p.a.'} hint={de ? 'Leer = 0 %' : 'Empty = 0 %'}><input type="number" min={0} max={100} step="0.01" value={form.interest_rate} onChange={e => set('interest_rate', e.target.value)} /></Field>
        </>}
      </div>
      <Field label={de ? 'Notiz' : 'Note'}><input maxLength={1000} value={form.note} onChange={e => set('note', e.target.value)} /></Field>
      <Feedback error={save.error} />
      <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>{de ? 'Abbrechen' : 'Cancel'}</Button><Button type="submit" busy={save.isPending}>{de ? 'Speichern' : 'Save'}</Button></div>
    </form>
  </Dialog>
}

type AsOf = { date: string; accounts: { id: string; name: string; balance?: string; mine?: string; observed_date?: string; flags: string[] }[]; total_mine: string; earmarked: { bucket: string; amount: string }[]; warnings: string[] }
const FLAG_DE: Record<string, string> = { no_opening_balance: 'kein Kontostand bis dahin', ambiguous_same_day: 'widersprüchliche Stände am selben Tag', observation_old: 'Kontostand älter als 45 Tage', closed_or_inactive: 'Konto inaktiv', settings_not_versioned: 'Einstellungen nicht historisiert' }
function AsOfPanel({ de, cur }: { de: boolean; cur: string }) {
  const [day, setDay] = useState('')
  const query = useQuery({ queryKey: ['as-of', day, cur], queryFn: () => api<AsOf>(`/as-of?date=${day}&currency=${cur}`), enabled: !!day })
  const d = query.data
  return <Panel title={de ? 'Stand an einem Stichtag' : 'Position on a past day'} description={de ? 'Rekonstruiert Kontostände, damals gültige Konto-Einstellungen und Zuteilungen. Es werden nie spätere Daten verwendet; Lücken werden markiert.' : 'Reconstructs balances, the account settings and earmarks that applied then. Later data is never used; gaps are flagged.'}>
    <Field label={de ? 'Stichtag' : 'Day'}><input type="date" max={new Date().toISOString().slice(0, 10)} value={day} onChange={e => setDay(e.target.value)} /></Field>
    <Feedback error={query.error} />
    {d && Array.isArray(d.accounts) && <>
      <p>{de ? 'Mein Anteil an den Kontoständen' : 'My share of balances'}: <Money value={d.total_mine} currency={cur} /></p>
      <table className="data-table"><tbody>{d.accounts.map(a => <tr key={a.id}><td>{a.name}</td><td>{a.mine != null ? <Money value={a.mine} currency={cur} /> : '—'}</td><td className="muted small">{a.flags.map(f => (de ? FLAG_DE[f] : f) ?? f).join(', ')}</td></tr>)}</tbody></table>
      {d.earmarked.length > 0 && <p className="muted small">{de ? 'Zugeteilt' : 'Earmarked'}: {d.earmarked.map(e => `${e.bucket} ${e.amount}`).join(', ')}</p>}
      {d.warnings.map((w, i) => <p className="muted small" key={i}>{localizeWarning(w, de ? 'de' : 'en')}</p>)}
    </>}
  </Panel>
}
