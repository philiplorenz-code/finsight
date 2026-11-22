import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Feedback, Field, Money, Panel } from './ui'

export type Term = { key: string; name: string; kind?: string | null; annual_cost?: string | null; status: string; notice_days: number; renew_months: number; note: string
  configured_term_end?: string | null; term_end?: string; cancel_by?: string; days_left?: number; expired?: boolean }

export function useTerms() {
  return useQuery({ queryKey: ['contract-terms'], queryFn: () => api<{ items: Term[] }>('/contract-terms') })
}

/** Deadlines panel for the contracts page: next chance to cancel per contract with stored terms. */
export function DeadlinePanel() {
  const { language } = useLocale(); const de = language === 'de'
  const terms = useTerms()
  const items = terms.data?.items ?? []
  if (!items.length) return null
  const tone = (t: Term) => t.expired ? '' : (t.days_left ?? 999) <= 14 ? 'danger' : (t.days_left ?? 999) <= 45 ? 'warning' : 'success'
  return <Panel title={de ? 'Kündigungsfristen' : 'Cancellation deadlines'} action={<AlarmClock size={18} />} description={de ? 'Bis wann du spätestens kündigen musst, damit sich der Vertrag nicht verlängert.' : 'The last day to cancel before the contract renews.'}>
    <DataTable headers={[de ? 'Vertrag' : 'Contract', de ? 'Kündigen bis' : 'Cancel by', de ? 'Laufzeit bis' : 'Term ends', de ? 'Kosten/Jahr' : 'Cost/year', '']}>
      {items.map(t => <tr key={t.key}><td>{t.name}{t.note && <div className="small muted">{t.note}</div>}</td>
        <td className="nowrap">{t.cancel_by ? formatDate(t.cancel_by, language) : '—'}</td>
        <td className="nowrap small">{t.term_end ? formatDate(t.term_end, language) : '—'}{t.renew_months ? <div className="muted">{de ? `verlängert sich um ${t.renew_months} Mon.` : `renews ${t.renew_months} mo.`}</div> : null}</td>
        <td>{t.annual_cost ? <Money value={t.annual_cost} /> : '—'}</td>
        <td><Badge tone={tone(t)}>{t.expired ? (de ? 'abgelaufen' : 'ended') : de ? `noch ${t.days_left} Tage` : `${t.days_left} days left`}</Badge></td></tr>)}
    </DataTable>
  </Panel>
}

/** Form inside the contract detail dialog. */
export function TermForm({ contractKey }: { contractKey: string }) {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const terms = useTerms()
  const current = terms.data?.items.find(t => t.key === contractKey)
  const [form, setForm] = useState<{ term_end: string; notice_days: string; renew_months: string; note: string } | null>(null)
  const value = form ?? { term_end: current?.configured_term_end ?? '', notice_days: String(current?.notice_days ?? 30), renew_months: String(current?.renew_months ?? 12), note: current?.note ?? '' }
  const done = () => { client.invalidateQueries({ queryKey: ['contract-terms'] }); client.invalidateQueries({ queryKey: ['upcoming'] }); setForm(null) }
  const save = useMutation({ mutationFn: () => send(`/contract-terms?key=${encodeURIComponent(contractKey)}`, { term_end: value.term_end || null, notice_days: Number(value.notice_days) || 0, renew_months: Number(value.renew_months) || 0, note: value.note }, 'PUT'), onSuccess: done })
  const remove = useMutation({ mutationFn: () => send(`/contract-terms?key=${encodeURIComponent(contractKey)}`, undefined, 'DELETE'), onSuccess: done })
  return <form className="form-stack term-form" onSubmit={e => { e.preventDefault(); save.mutate() }}>
    <h3>{de ? 'Laufzeit & Kündigung' : 'Term & cancellation'}</h3>
    {current?.cancel_by && <p className="small">{de ? 'Nächste Kündigungsmöglichkeit' : 'Next chance to cancel'}: <strong>{formatDate(current.cancel_by, language)}</strong></p>}
    <div className="form-grid">
      <Field label={de ? 'Laufzeit endet am' : 'Term ends on'}><input type="date" value={value.term_end} onChange={e => setForm({ ...value, term_end: e.target.value })} /></Field>
      <Field label={de ? 'Kündigungsfrist (Tage)' : 'Notice (days)'}><input type="number" min={0} max={730} value={value.notice_days} onChange={e => setForm({ ...value, notice_days: e.target.value })} /></Field>
      <Field label={de ? 'Verlängert sich um (Monate, 0 = nicht)' : 'Renews by (months, 0 = no)'}><input type="number" min={0} max={120} value={value.renew_months} onChange={e => setForm({ ...value, renew_months: e.target.value })} /></Field>
      <Field label={de ? 'Notiz' : 'Note'}><input maxLength={300} value={value.note} onChange={e => setForm({ ...value, note: e.target.value })} /></Field>
    </div>
    <Feedback error={save.error || remove.error} />
    <div className="form-actions">{current && <Button type="button" variant="ghost" onClick={() => remove.mutate()}>{de ? 'Frist entfernen' : 'Remove'}</Button>}<Button busy={save.isPending}>{de ? 'Frist speichern' : 'Save term'}</Button></div>
  </form>
}
