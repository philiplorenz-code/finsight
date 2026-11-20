import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Landmark } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { Button, DataTable, Dialog, Feedback, Money, Notice } from './ui'

type Item = { id: string; name: string; currency: string; balance: string | null; bookings: number; last_booking: string | null; suggestion: { ownership: string; purpose: string; reason: string } }
type Unclassified = { count: number; items: Item[] }
type Choice = { ownership: string; purpose: string; included: boolean }

export const PURPOSE_DE: Record<string, string> = { checking: 'Girokonto', savings: 'Sparen / Rücklage', investment: 'Depot / Anlage', credit: 'Kreditkarte / Kredit', cash: 'Bargeld', other: 'Sonstiges', mirror: 'Spiegelkonto (z. B. PayPal, doppelt zur Bank)' }
export const PURPOSE_EN: Record<string, string> = { checking: 'Current account', savings: 'Savings / pot', investment: 'Investment', credit: 'Credit', cash: 'Cash', other: 'Other', mirror: 'Mirror (e.g. PayPal, duplicates bank)' }

/** Reminder for accounts that arrived with an import and still have unknown ownership (they count nowhere until decided). */
export function NewAccountsPrompt() {
  const { language } = useLocale()
  const de = language === 'de'
  const query = useQuery({ queryKey: ['unclassified-accounts'], queryFn: () => api<Unclassified>('/accounts/unclassified'), retry: false })
  const [open, setOpen] = useState(false)
  const data = query.data
  if (!data || !Array.isArray(data.items) || !data.count) return null
  return <>
    <Notice warning>
      <span>{de ? `${data.count} Konto/Konten warten auf deine Einordnung und zählen bis dahin nirgends mit.` : `${data.count} account(s) wait for your decision and count nowhere until then.`}</span>{' '}
      <Button variant="outline" onClick={() => setOpen(true)}><Landmark size={15} />{de ? 'Jetzt einordnen' : 'Classify now'}</Button>
    </Notice>
    {open && <ClassifyDialog items={data.items} de={de} onClose={() => setOpen(false)} />}
  </>
}

function ClassifyDialog({ items, de, onClose }: { items: Item[]; de: boolean; onClose: () => void }) {
  const { language } = useLocale()
  const client = useQueryClient()
  const initial = Object.fromEntries(items.map(i => [i.id, { ownership: i.suggestion.ownership, purpose: i.suggestion.purpose, included: true } as Choice]))
  const [choice, setChoice] = useState<Record<string, Choice>>(initial)
  const set = (id: string, patch: Partial<Choice>) => setChoice({ ...choice, [id]: { ...choice[id], ...patch } })
  const purposes = de ? PURPOSE_DE : PURPOSE_EN
  const save = useMutation({
    mutationFn: () => send('/accounts/classify', { items: items.map(i => ({ id: i.id, ...choice[i.id] })) }),
    onSuccess: () => { client.invalidateQueries(); onClose() },
  })
  return <Dialog title={de ? 'Neue Konten einordnen' : 'Classify new accounts'} onClose={onClose}>
    <p className="muted">{de ? 'Die Vorauswahl ist ein Vorschlag aus Name, Kontostand und Nutzung. Prüfe sie, bevor du speicherst. „Eigenes Konto“ heißt: Es zählt zu deinem Vermögen und deinen Auswertungen.' : 'The preselection is a suggestion from name, balance and usage. Check it before saving. "Own account" means it counts in your wealth and analysis.'}</p>
    <DataTable headers={[de ? 'Konto' : 'Account', de ? 'Stand' : 'Balance', de ? 'Gehört' : 'Ownership', de ? 'Verwendung' : 'Purpose', de ? 'Zählen' : 'Include']}>{items.map(i => <tr key={i.id}>
      <td><strong>{i.name}</strong><small className="block muted">{i.bookings} {de ? 'Buchungen' : 'bookings'}{i.last_booking ? ` · ${de ? 'zuletzt' : 'last'} ${formatDate(i.last_booking, language)}` : ''}</small></td>
      <td><Money value={i.balance} currency={i.currency} /></td>
      <td><select aria-label={`${i.name}: ${de ? 'Eigentum' : 'ownership'}`} value={choice[i.id].ownership} onChange={e => set(i.id, { ownership: e.target.value })}><option value="owned">{de ? 'Eigenes Konto' : 'Own account'}</option><option value="external">{de ? 'Fremdes Konto' : 'Someone else\'s'}</option></select></td>
      <td><select aria-label={`${i.name}: ${de ? 'Verwendung' : 'purpose'}`} value={choice[i.id].purpose} onChange={e => set(i.id, { purpose: e.target.value })}>{Object.entries(purposes).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td>
      <td><input type="checkbox" aria-label={`${i.name}: ${de ? 'einbeziehen' : 'include'}`} checked={choice[i.id].included} onChange={e => set(i.id, { included: e.target.checked })} /></td></tr>)}</DataTable>
    <Feedback error={save.error} />
    <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>{de ? 'Später' : 'Later'}</Button><Button busy={save.isPending} onClick={() => save.mutate()}>{de ? 'Speichern' : 'Save'}</Button></div>
  </Dialog>
}
