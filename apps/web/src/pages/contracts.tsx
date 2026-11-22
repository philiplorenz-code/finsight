import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check, ChevronRight, EyeOff, RotateCcw } from 'lucide-react'
import { api, items, send } from '../lib/api'
import type { Contract } from '../lib/types'
import { normalizeContract, type RawContract } from '../lib/adapters'
import { formatDate, useLocale } from '../lib/i18n'
import { DeadlinePanel, TermForm } from '../components/contract-terms'
import { label } from '../lib/labels'
import { localizeWarning } from '../lib/warnings'
import { Badge, Button, DataTable, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Extra = { key?: string; kind?: string; status?: string; decision?: string | null; monthly_cost?: string | null; charges?: number; price_change?: string | null; last_charge?: string | null }
type Row = Contract & Extra
type RawRow = RawContract & Extra
type Totals = Record<string, { monthly: string; yearly: string; by_kind: Record<string, { monthly: string; yearly: string; count: number }> }>
type Candidate = { key: string; name: string; kind: string; currency: string; annual_cost: string; period: string; price_increase: boolean }
type Payload = { items: RawRow[]; dismissed?: RawRow[]; totals?: Totals; cancellation_candidates?: Candidate[]; warnings?: string[] }

const KINDS = ['insurance', 'housing', 'loan', 'subscription', 'utility', 'savings', 'other'] as const
const KIND_DE: Record<string, string> = { insurance: 'Versicherung', housing: 'Wohnen', loan: 'Kredit / Rate', subscription: 'Abo', utility: 'Nebenkosten / Telefon', savings: 'Sparen / Anlage', other: 'Sonstiges' }
const KIND_EN: Record<string, string> = { insurance: 'Insurance', housing: 'Housing', loan: 'Loan', subscription: 'Subscription', utility: 'Utilities', savings: 'Savings plan', other: 'Other' }
const PERIOD_DE: Record<string, string> = { monthly: 'monatlich', quarterly: 'vierteljährlich', half_yearly: 'halbjährlich', yearly: 'jährlich', unknown: '—' }
const PERIOD_EN: Record<string, string> = { monthly: 'monthly', quarterly: 'quarterly', half_yearly: 'half-yearly', yearly: 'yearly', unknown: '—' }

export default function ContractsPage() {
  const { t, language } = useLocale()
  const de = language === 'de'
  const client = useQueryClient()
  const kindName = (k?: string) => (de ? KIND_DE : KIND_EN)[k ?? 'other'] ?? k ?? '—'
  const periodName = (p?: string) => (de ? PERIOD_DE : PERIOD_EN)[p ?? 'unknown'] ?? p ?? '—'
  const query = useQuery({ queryKey: ['contracts'], queryFn: async () => {
    const data = await api<Payload>('/contracts')
    const norm = (list: RawRow[] | undefined) => (list ?? []).map((c, i) => normalizeContract(c, i) as Row)
    return { items: items(data).map((c, i) => normalizeContract(c as RawRow, i) as Row), dismissed: norm(data.dismissed), totals: data.totals ?? {}, candidates: data.cancellation_candidates ?? [], warnings: data.warnings }
  } })
  const [detail, setDetail] = useState<Row | null>(null)
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<string>('all')
  const [sort, setSort] = useState<'cost' | 'name' | 'next'>('cost')
  const [onlyUp, setOnlyUp] = useState(false)
  const data = query.data
  const active = data?.items.filter(c => c.status !== 'stopped') ?? []
  const stopped = data?.items.filter(c => c.status === 'stopped') ?? []
  const currency = Object.keys(data?.totals ?? {})[0]
  const total = currency ? data?.totals[currency] : undefined
  const decide = useMutation({
    mutationFn: (v: { key: string; decision: 'confirm' | 'dismiss' | 'reset'; name?: string; kind?: string }) => send('/contracts/decision', v, 'PUT'),
    onSuccess: () => { client.invalidateQueries({ queryKey: ['contracts'] }); client.invalidateQueries({ queryKey: ['analytics'] }); setDetail(null) },
  })
  const table = (rows: Row[]) => <DataTable headers={[t('name'), de ? 'Rhythmus' : 'Rhythm', de ? 'Pro Monat' : 'Per month', t('annual'), t('nextCharge'), t('confidence'), '']}>{rows.map(c => <tr key={c.id}>
    <td><strong>{c.name}</strong> {c.kind && <Badge>{kindName(c.kind)}</Badge>}{c.decision === 'confirmed' && <Badge tone="success"><Check size={12} /></Badge>}<small className="block muted">{c.source || t('inferred')}{c.charges ? ` · ${c.charges}×` : ''}</small></td>
    <td>{periodName(c.frequency)}</td><td><Money value={c.monthly_cost} currency={c.currency} /></td><td><Money value={c.annualized_cost} currency={c.currency} /></td>
    <td>{c.status === 'stopped' ? (de ? 'beendet' : 'stopped') : formatDate(c.next_charge, language)}</td><td><Badge>{label('confidence', c.confidence == null ? null : String(c.confidence), language)}</Badge></td>
    <td><Button variant="ghost" onClick={() => setDetail(c)} aria-label={`${t('details')}: ${c.name}`}><ChevronRight size={18} /></Button></td></tr>)}</DataTable>
  return <><PageHeader title={t('contracts')} description={t('contractsIntro')} /><Notice>{t('contractNote')}</Notice>{data?.warnings?.map((w, i) => <Notice key={i} warning>{localizeWarning(w, language)}</Notice>)}
    {total && currency && <div className="contract-summary">
      <div className="contract-total"><span>{de ? 'Laufende Verträge pro Monat' : 'Running contracts per month'}</span><Money value={total.monthly} currency={currency} /><small className="muted">{de ? 'pro Jahr' : 'per year'} <Money value={total.yearly} currency={currency} /> · {active.length} {de ? 'Verträge' : 'contracts'}</small></div>
      <div className="kind-bars">{KINDS.filter(k => total.by_kind?.[k]).sort((a, b) => Number(total.by_kind[b].monthly) - Number(total.by_kind[a].monthly)).map(k => {
        const share = Number(total.monthly) ? Number(total.by_kind[k].monthly) / Number(total.monthly) * 100 : 0
        return <button type="button" key={k} className={`kind-bar ${kind === k ? 'active' : ''}`} onClick={() => setKind(kind === k ? 'all' : k)}>
          <span className="kind-bar-label">{kindName(k)} <small className="muted">{total.by_kind[k].count}</small></span>
          <span className="kind-bar-track"><span style={{ width: `${Math.max(2, share)}%` }} /></span>
          <Money value={total.by_kind[k].monthly} currency={currency} />
        </button>
      })}</div>
    </div>}
    {!!data?.candidates.length && <Panel title={de ? 'Prüfen: kündigen oder neu verhandeln' : 'Review: cancel or renegotiate'} description={de ? 'Versicherungen, Abos und nicht eingeordnete Kosten, nach Jahreskosten sortiert. Eine Empfehlung zum Kündigen ist das nicht, nur eine Prüfliste.' : 'Insurances, subscriptions and unclassified costs by yearly cost. A checklist, not advice to cancel.'}>
      <ul className="obligation-list">{data.candidates.map(c => <li key={c.key}><span>{c.name} · {kindName(c.kind)} · {periodName(c.period)}{c.price_increase && <> · <Badge tone="warning">{de ? 'Preis gestiegen' : 'price up'}</Badge></>}</span><Money value={c.annual_cost} currency={c.currency} /></li>)}</ul>
    </Panel>}
    <DeadlinePanel />
    <div className="contract-toolbar">
      <input type="search" aria-label={de ? 'Verträge durchsuchen' : 'Search contracts'} placeholder={de ? 'Vertrag suchen …' : 'Search contract…'} value={search} onChange={e => setSearch(e.target.value)} />
      <select aria-label={de ? 'Art' : 'Kind'} value={kind} onChange={e => setKind(e.target.value)}><option value="all">{de ? 'Alle Arten' : 'All kinds'}</option>{KINDS.map(k => <option key={k} value={k}>{kindName(k)}</option>)}</select>
      <select aria-label={de ? 'Sortierung' : 'Sort'} value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="cost">{de ? 'Teuerste zuerst' : 'Most expensive'}</option><option value="next">{de ? 'Nächste Abbuchung' : 'Next charge'}</option><option value="name">{de ? 'Name' : 'Name'}</option></select>
      <label className="checkbox"><input type="checkbox" checked={onlyUp} onChange={e => setOnlyUp(e.target.checked)} />{de ? 'Nur Preiserhöhungen' : 'Price increases only'}</label>
    </div>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!data?.items.length}>{(() => {
      const needle = search.trim().toLowerCase()
      const rows = active.filter(c => (kind === 'all' || (c.kind ?? 'other') === kind) && (!needle || c.name.toLowerCase().includes(needle)) && (!onlyUp || Number(c.price_change ?? 0) > 0))
      const sorted = [...rows].sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'next' ? String(a.next_charge ?? '9').localeCompare(String(b.next_charge ?? '9')) : Number(b.monthly_cost ?? 0) - Number(a.monthly_cost ?? 0))
      const groups = KINDS.map(k => ({ k, rows: sorted.filter(c => (c.kind ?? 'other') === k) })).filter(g => g.rows.length)
      if (!groups.length) return <p className="muted">{de ? 'Keine Verträge für diesen Filter.' : 'No contracts for this filter.'}</p>
      return groups.map(g => <section key={g.k} className="contract-group">
        <h3>{kindName(g.k)} <small className="muted">{g.rows.length} · <Money value={String(g.rows.reduce((s2, c) => s2 + Number(c.monthly_cost ?? 0), 0))} currency={g.rows[0].currency} /> {de ? 'pro Monat' : 'per month'}</small></h3>
        <div className="contract-cards">{g.rows.map(c => <button type="button" key={c.id} className="contract-card" onClick={() => setDetail(c)} aria-label={`${t('details')}: ${c.name}`}>
          <span className="contract-card-top"><strong>{c.name}</strong>{c.decision === 'confirmed' && <Check size={14} aria-label={de ? 'bestätigt' : 'confirmed'} />}</span>
          <span className="contract-card-cost"><Money value={c.monthly_cost} currency={c.currency} /><small className="muted">/{de ? 'Monat' : 'month'}</small></span>
          <span className="contract-card-meta muted small">{periodName(c.frequency)} · <Money value={c.annualized_cost} currency={c.currency} /> {de ? 'im Jahr' : 'a year'}</span>
          <span className="contract-card-meta small">{de ? 'Nächste' : 'Next'}: {formatDate(c.next_charge, language)}</span>
          <span className="badge-row">{Number(c.price_change ?? 0) > 0 && <Badge tone="warning">{de ? 'Preis +' : 'Price +'}{Number(c.price_change).toLocaleString(de ? 'de-DE' : 'en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €</Badge>}{c.confidence && String(c.confidence) !== 'high' && <Badge>{de ? 'Sicherheit' : 'Confidence'}: {label('confidence', String(c.confidence), language)}</Badge>}</span>
        </button>)}</div>
      </section>)
    })()}</QueryState>
    {!!stopped.length && <Panel><details><summary>{de ? `Beendet (${stopped.length}) – seit mehr als 1,6 Zahlungsperioden keine Abbuchung` : `Stopped (${stopped.length}) – no charge for more than 1.6 billing periods`}</summary>{table(stopped)}</details></Panel>}
    {!!data?.dismissed.length && <Panel><details><summary>{de ? `Verworfen (${data.dismissed.length})` : `Dismissed (${data.dismissed.length})`}</summary><ul className="obligation-list">{data.dismissed.map(c => <li key={c.id}><span>{c.name}</span><Button variant="ghost" onClick={() => c.key && decide.mutate({ key: c.key, decision: 'reset' })}><RotateCcw size={14} />{de ? 'Wiederherstellen' : 'Restore'}</Button></li>)}</ul></details></Panel>}
    <Feedback error={decide.error} />
    {detail && <ContractDetail detail={detail} de={de} kindName={kindName} busy={decide.isPending} onClose={() => setDetail(null)} onDecide={decide.mutate} />}</>
}

function ContractDetail({ detail, de, kindName, busy, onClose, onDecide }: { detail: Row; de: boolean; kindName: (k?: string) => string; busy: boolean; onClose: () => void; onDecide: (v: { key: string; decision: 'confirm' | 'dismiss' | 'reset'; name?: string; kind?: string }) => void }) {
  const { t, language } = useLocale()
  const [name, setName] = useState(detail.name)
  const [kind, setKind] = useState(detail.kind ?? 'other')
  return <Dialog title={detail.name} onClose={onClose}>
    <div className="detail-stat"><span>{t('annual')}</span><Money value={detail.annualized_cost} currency={detail.currency} /></div>
    {detail.price_change != null && <div className="detail-stat"><span>{de ? 'Preisänderung' : 'Price change'}</span><Money value={detail.price_change} currency={detail.currency} /></div>}
    {detail.key && <>
      <div className="form-grid">
        <Field label={de ? 'Name' : 'Name'}><input maxLength={300} value={name} onChange={e => setName(e.target.value)} /></Field>
        <Field label={de ? 'Art' : 'Kind'}><select value={kind} onChange={e => setKind(e.target.value)}>{KINDS.map(k => <option key={k} value={k}>{kindName(k)}</option>)}</select></Field>
      </div>
      <div className="form-actions">
        <Button variant="outline" disabled={busy} onClick={() => onDecide({ key: detail.key!, decision: 'dismiss' })}><EyeOff size={15} />{de ? 'Kein Vertrag' : 'Not a contract'}</Button>
        {detail.decision && <Button variant="ghost" disabled={busy} onClick={() => onDecide({ key: detail.key!, decision: 'reset' })}>{de ? 'Zurücksetzen' : 'Reset'}</Button>}
        <Button busy={busy} onClick={() => onDecide({ key: detail.key!, decision: 'confirm', name: name.trim() || detail.name, kind })}><Check size={15} />{de ? 'Bestätigen' : 'Confirm'}</Button>
      </div>
    </>}
    <h3>{t('evidence')}</h3><ul className="evidence-list">{detail.evidence?.map((e, i) => <li key={i}>{e.description}{e.transaction_id && <Link to={`/transactions?detail=${encodeURIComponent(e.transaction_id)}`}>{t('transactions')} →</Link>}</li>)}</ul>{!detail.evidence?.length && <p className="muted">{t('noValue')}</p>}
    {detail.key && <TermForm contractKey={detail.key} />}
  </Dialog>
}
