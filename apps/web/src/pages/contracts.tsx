import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check, ChevronRight, EyeOff, RotateCcw } from 'lucide-react'
import { api, items, send } from '../lib/api'
import type { Contract } from '../lib/types'
import { normalizeContract, type RawContract } from '../lib/adapters'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Extra = { key?: string; kind?: string; status?: string; decision?: string | null; monthly_cost?: string | null; charges?: number }
type Row = Contract & Extra
type RawRow = RawContract & Extra
type Totals = Record<string, { monthly: string; yearly: string; by_kind: Record<string, { monthly: string; yearly: string; count: number }> }>
type Candidate = { key: string; name: string; kind: string; currency: string; annual_cost: string; period: string; price_increase: boolean }
type Payload = { items: RawRow[]; dismissed?: RawRow[]; totals?: Totals; cancellation_candidates?: Candidate[]; warnings?: string[] }

const KINDS = ['insurance', 'housing', 'loan', 'subscription', 'utility', 'other'] as const
const KIND_DE: Record<string, string> = { insurance: 'Versicherung', housing: 'Wohnen', loan: 'Kredit / Rate', subscription: 'Abo', utility: 'Nebenkosten / Telefon', other: 'Sonstiges' }
const KIND_EN: Record<string, string> = { insurance: 'Insurance', housing: 'Housing', loan: 'Loan', subscription: 'Subscription', utility: 'Utilities', other: 'Other' }
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
    <td>{c.status === 'stopped' ? (de ? 'beendet' : 'stopped') : formatDate(c.next_charge, language)}</td><td><Badge>{c.confidence ?? '—'}</Badge></td>
    <td><Button variant="ghost" onClick={() => setDetail(c)} aria-label={`${t('details')}: ${c.name}`}><ChevronRight size={18} /></Button></td></tr>)}</DataTable>
  return <><PageHeader title={t('contracts')} description={t('contractsIntro')} /><Notice>{t('contractNote')}</Notice>{data?.warnings?.map((w, i) => <Notice key={i} warning>{w}</Notice>)}
    {total && currency && <Panel title={de ? 'Feste Kosten im Überblick' : 'Fixed costs at a glance'} description={de ? 'Nur laufende Verträge; beendete und verworfene zählen nicht.' : 'Running contracts only; stopped and dismissed ones are not counted.'}>
      <div className="stat-grid">
        <div className="detail-stat"><span>{de ? 'Pro Monat' : 'Per month'}</span><Money value={total.monthly} currency={currency} /></div>
        <div className="detail-stat"><span>{de ? 'Pro Jahr' : 'Per year'}</span><Money value={total.yearly} currency={currency} /></div>
        {KINDS.filter(k => total.by_kind?.[k]).map(k => <div className="detail-stat" key={k}><span>{kindName(k)} · {total.by_kind[k].count}</span><Money value={total.by_kind[k].yearly} currency={currency} /><small className="muted">{de ? 'pro Jahr' : 'per year'}</small></div>)}
      </div>
    </Panel>}
    {!!data?.candidates.length && <Panel title={de ? 'Prüfen: kündigen oder neu verhandeln' : 'Review: cancel or renegotiate'} description={de ? 'Versicherungen, Abos und nicht eingeordnete Kosten, nach Jahreskosten sortiert. Eine Empfehlung zum Kündigen ist das nicht, nur eine Prüfliste.' : 'Insurances, subscriptions and unclassified costs by yearly cost. A checklist, not advice to cancel.'}>
      <ul className="obligation-list">{data.candidates.map(c => <li key={c.key}><span>{c.name} · {kindName(c.kind)} · {periodName(c.period)}{c.price_increase && <> · <Badge tone="warning">{de ? 'Preis gestiegen' : 'price up'}</Badge></>}</span><Money value={c.annual_cost} currency={c.currency} /></li>)}</ul>
    </Panel>}
    <Panel><QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!data?.items.length}>{table(active)}</QueryState></Panel>
    {!!stopped.length && <Panel title={de ? 'Beendet' : 'Stopped'} description={de ? 'Seit mehr als 1,6 Zahlungsperioden keine Abbuchung mehr.' : 'No charge for more than 1.6 billing periods.'}>{table(stopped)}</Panel>}
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
  </Dialog>
}
