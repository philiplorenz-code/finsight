import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import type { RawBucket } from '../lib/adapters'
import { Button, Dialog, Feedback, Field, Money, Notice } from './ui'

type Event = { id: string; recorded_at: string; amount: string; account_name?: string | null }
type Obligation = NonNullable<RawBucket['obligations']>[number]

export function BucketManage({ bucket, onClose }: { bucket: RawBucket; onClose: () => void }) {
  const { language } = useLocale(); const de = language === 'de'; const client = useQueryClient()
  const [name, setName] = useState(bucket.name)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const refresh = () => { client.invalidateQueries({ queryKey: ['buckets'] }); client.invalidateQueries({ queryKey: ['overview'] }) }
  const rename = useMutation({ mutationFn: () => send(`/buckets/${encodeURIComponent(bucket.id)}`, { name }, 'PATCH'), onSuccess: () => { refresh(); onClose() } })
  const remove = useMutation({ mutationFn: () => send(`/buckets/${encodeURIComponent(bucket.id)}`, undefined, 'DELETE'), onSuccess: () => { refresh(); onClose() } })
  const history = useQuery({ queryKey: ['allocation-history', bucket.id], queryFn: () => api<Event[]>(`/buckets/${encodeURIComponent(bucket.id)}/allocation-history`) })
  return <Dialog title={`${de ? 'Verwalten' : 'Manage'}: ${bucket.name}`} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); rename.mutate() }}>
      <Field label={de ? 'Name' : 'Name'}><input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></Field>
      <Feedback error={rename.error} /><Button busy={rename.isPending} disabled={!name.trim() || name === bucket.name}>{de ? 'Umbenennen' : 'Rename'}</Button>
    </form>
    {!!bucket.obligations?.length && <>
      <h3>{de ? 'Verpflichtungen' : 'Obligations'}</h3>
      {bucket.obligations.map(o => <ObligationRow key={o.id} bucketId={bucket.id} o={o} currency={bucket.currency} de={de} onDone={refresh} />)}
    </>}
    <h3>{de ? 'Verlauf der Zuteilungen' : 'Allocation history'}</h3>
    {history.data?.length ? <ul className="obligation-list">{history.data.slice(0, 20).map(e => <li key={e.id}><span>{formatDate(e.recorded_at, language)} · {Number(e.amount) === 0 && !e.account_name ? (de ? 'Zuteilung aufgehoben' : 'released') : e.account_name ?? '—'}</span>{Number(e.amount) > 0 && <Money value={e.amount} currency={bucket.currency} />}</li>)}</ul>
      : <p className="muted small">{de ? 'Noch keine Zuteilung gespeichert.' : 'No allocation saved yet.'}</p>}
    <h3>{de ? 'Löschen' : 'Delete'}</h3>
    <Notice warning>{de ? 'Löscht nur den Topf mit Zuteilungen und Verpflichtungen. Buchungen und Kontostände bleiben unberührt; der Zuteilungsverlauf bleibt erhalten.' : 'Deletes only the bucket with its allocations and obligations. Transactions and balances are untouched; allocation history is kept.'}</Notice>
    {confirmDelete
      ? <div className="form-actions"><Button variant="outline" onClick={() => setConfirmDelete(false)}>{de ? 'Abbrechen' : 'Cancel'}</Button><Button busy={remove.isPending} onClick={() => remove.mutate()}><Trash2 size={15} />{de ? 'Endgültig löschen' : 'Delete for good'}</Button></div>
      : <Button variant="outline" onClick={() => setConfirmDelete(true)}><Trash2 size={15} />{de ? 'Topf löschen …' : 'Delete bucket …'}</Button>}
    <Feedback error={remove.error} />
  </Dialog>
}

function ObligationRow({ bucketId, o, currency, de, onDone }: { bucketId: string; o: Obligation; currency: string; de: boolean; onDone: () => void }) {
  const [name, setName] = useState(o.name)
  const [amount, setAmount] = useState(String(o.amount))
  const url = `/buckets/${encodeURIComponent(bucketId)}/obligations/${encodeURIComponent(o.id)}`
  const save = useMutation({ mutationFn: () => send(url, { name, amount }, 'PATCH'), onSuccess: onDone })
  const del = useMutation({ mutationFn: () => send(url, undefined, 'DELETE'), onSuccess: onDone })
  return <div className="form-grid" role="group" aria-label={o.name}>
    <input aria-label={`${o.name}: ${de ? 'Name' : 'name'}`} value={name} maxLength={300} onChange={e => setName(e.target.value)} />
    <input aria-label={`${o.name}: ${de ? 'Betrag' : 'amount'} (${currency})`} type="number" min="0.01" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} />
    <div className="form-actions"><Button variant="outline" busy={save.isPending} disabled={!name.trim() || Number(amount) <= 0 || (name === o.name && Number(amount) === Number(o.amount))} onClick={() => save.mutate()}>{de ? 'Speichern' : 'Save'}</Button>
      <Button variant="ghost" aria-label={`${de ? 'Verpflichtung löschen' : 'Delete obligation'}: ${o.name}`} busy={del.isPending} onClick={() => del.mutate()}><Trash2 size={15} /></Button></div>
    <Feedback error={save.error ?? del.error} />
  </div>
}
