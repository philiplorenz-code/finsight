import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Item = { id: string; direction: 'receivable' | 'payable'; person: string; title: string; amount: string; since: string; due?: string | null
  status: 'open' | 'settled' | 'dropped'; settled_on?: string | null; note: string; overdue: boolean
  suggested_settlement?: { transaction_id: string; date: string; merchant: string; account: string; name_matches: boolean } | null }
type Data = { items: Item[]; totals: { receivable: string; payable: string; net: string } }

export default function OpenItemsPage() {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['open-items'], queryFn: () => api<Data>('/open-items') })
  const [create, setCreate] = useState<'receivable' | 'payable' | null>(null)
  const refresh = () => client.invalidateQueries({ queryKey: ['open-items'] })
  const patch = useMutation({ mutationFn: ({ id, body }: { id: string; body: object }) => send(`/open-items/${encodeURIComponent(id)}`, body, 'PATCH'), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: string) => send(`/open-items/${encodeURIComponent(id)}`, undefined, 'DELETE'), onSuccess: refresh })
  const d = query.data
  const column = (direction: Item['direction']) => {
    const rows = (d?.items ?? []).filter(i => i.direction === direction && i.status === 'open')
    return <Panel title={direction === 'receivable' ? (de ? 'Bekomme ich zurück' : 'Owed to me') : (de ? 'Schulde ich' : 'I owe')}
      action={<Button variant="outline" onClick={() => setCreate(direction)}><Plus size={15} />{de ? 'Posten' : 'Item'}</Button>}
>
      {d && <p className="open-total"><Money value={direction === 'receivable' ? d.totals.receivable : d.totals.payable} /></p>}
      {!rows.length ? <p className="muted">{de ? 'Nichts offen.' : 'Nothing open.'}</p> : <ul className="open-list">{rows.map(i => <li key={i.id}>
        <div className="open-head"><strong>{i.title}</strong><Money value={i.amount} /></div>
        <div className="small muted">{i.person} · {de ? 'seit' : 'since'} {formatDate(i.since, language)}{i.due ? ` · ${de ? 'fällig' : 'due'} ${formatDate(i.due, language)}` : ''}{i.note ? ` · ${i.note}` : ''}</div>
        {i.overdue && <Badge tone="warning">{de ? 'überfällig' : 'overdue'}</Badge>}
        {i.suggested_settlement && <div className="open-suggest">
          <span>{de ? 'Passende Zahlung gefunden' : 'Matching payment found'}: {formatDate(i.suggested_settlement.date, language)} · {i.suggested_settlement.merchant} · {i.suggested_settlement.account}{!i.suggested_settlement.name_matches && <em> ({de ? 'Name passt nicht sicher' : 'name not certain'})</em>}</span>
          <Button variant="outline" busy={patch.isPending} onClick={() => patch.mutate({ id: i.id, body: { settled_transaction_id: i.suggested_settlement!.transaction_id } })}><Check size={14} />{de ? 'Als erledigt markieren' : 'Mark settled'}</Button>
        </div>}
        <div className="open-actions">
          <Button variant="ghost" onClick={() => patch.mutate({ id: i.id, body: { status: 'settled' } })}>{de ? 'Erledigt' : 'Settled'}</Button>
          <Button variant="ghost" onClick={() => patch.mutate({ id: i.id, body: { status: 'dropped' } })}>{de ? 'Verworfen' : 'Drop'}</Button>
          <Button variant="ghost" aria-label={`${de ? 'Löschen' : 'Delete'}: ${i.title}`} onClick={() => remove.mutate(i.id)}><Trash2 size={15} /></Button>
        </div>
      </li>)}</ul>}
    </Panel>
  }
  const done = (d?.items ?? []).filter(i => i.status !== 'open')
  return <>
    <PageHeader title={de ? 'Offene Posten' : 'Open items'} description={de ? 'Geld, das du von jemandem zurückbekommst oder jemandem schuldest. Kommt eine passende Zahlung, schlägt FinSight vor, den Posten abzuhaken.' : 'Money someone owes you or you owe someone. When a matching payment arrives, FinSight suggests settling it.'} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{d && <>
      <Notice>{de ? 'Saldo offener Posten' : 'Net open items'}: <strong><Money value={d.totals.net} /></strong> {Number(d.totals.net) >= 0 ? (de ? 'bekommst du unterm Strich.' : 'owed to you overall.') : (de ? 'schuldest du unterm Strich.' : 'you owe overall.')}</Notice>
      <div className="open-grid">{column('receivable')}{column('payable')}</div>
      {!!done.length && <Panel><details><summary>{de ? `Erledigt und verworfen (${done.length})` : `Settled and dropped (${done.length})`}</summary>
        <ul className="open-list">{done.map(i => <li key={i.id}><div className="open-head"><span>{i.title} · {i.person}</span><Money value={i.amount} /></div>
          <div className="small muted">{i.status === 'settled' ? (de ? `erledigt ${i.settled_on ? formatDate(i.settled_on, language) : ''}` : 'settled') : (de ? 'verworfen' : 'dropped')}
            <Button variant="ghost" onClick={() => patch.mutate({ id: i.id, body: { status: 'open' } })}><RotateCcw size={13} />{de ? 'wieder öffnen' : 'reopen'}</Button></div></li>)}</ul>
      </details></Panel>}
      <Feedback error={patch.error || remove.error} />
    </>}</QueryState>
    {create && <ItemForm direction={create} onClose={() => setCreate(null)} onDone={refresh} />}
  </>
}

function ItemForm({ direction, onClose, onDone }: { direction: 'receivable' | 'payable'; onClose: () => void; onDone: () => void }) {
  const { language } = useLocale(); const de = language === 'de'
  const [form, setForm] = useState({ person: '', title: '', amount: '', since: '', due: '', note: '' })
  const save = useMutation({ mutationFn: () => send('/open-items', { direction, ...form, since: form.since || null, due: form.due || null }), onSuccess: () => { onDone(); onClose() } })
  return <Dialog title={direction === 'receivable' ? (de ? 'Bekomme ich zurück' : 'Owed to me') : (de ? 'Schulde ich' : 'I owe')} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate() }}>
      <div className="form-grid">
        <Field label={de ? 'Wer' : 'Who'}><input id="oi-person" required maxLength={120} value={form.person} onChange={e => setForm({ ...form, person: e.target.value })} /></Field>
        <Field label={de ? 'Betrag (€)' : 'Amount (€)'}><input id="oi-amount" required type="number" min="0.01" step="0.01" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></Field>
      </div>
      <Field label={de ? 'Wofür' : 'What for'}><input id="oi-title" required maxLength={200} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></Field>
      <div className="form-grid">
        <Field label={de ? 'Offen seit' : 'Open since'} hint={de ? 'Zahlungen ab diesem Tag werden zum Abhaken vorgeschlagen.' : 'Payments from this day are suggested.'}><input id="oi-since" type="date" value={form.since} onChange={e => setForm({ ...form, since: e.target.value })} /></Field>
        <Field label={de ? 'Fällig bis' : 'Due by'}><input id="oi-due" type="date" value={form.due} onChange={e => setForm({ ...form, due: e.target.value })} /></Field>
      </div>
      <Field label={de ? 'Notiz' : 'Note'}><input id="oi-note" maxLength={300} value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} /></Field>
      <Feedback error={save.error} />
      <div className="form-actions"><Button type="button" variant="outline" onClick={onClose}>{de ? 'Abbrechen' : 'Cancel'}</Button><Button busy={save.isPending}>{de ? 'Speichern' : 'Save'}</Button></div>
    </form>
  </Dialog>
}
