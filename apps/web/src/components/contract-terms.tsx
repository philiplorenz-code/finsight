import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, CalendarPlus, Copy, FileSignature, Printer, Undo2 } from 'lucide-react'
import { api, send } from '../lib/api'
import { cancelLetter, deadlineIcs, type Sender } from '../lib/cancel-letter'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Dialog, Feedback, Field, Money, Notice, Panel } from './ui'

export type Term = { key: string; name: string; kind?: string | null; annual_cost?: string | null; status: string; notice_days: number; renew_months: number; note: string
  customer_number?: string; cancelled?: boolean; cancelled_on?: string | null; ended?: boolean
  configured_term_end?: string | null; term_end?: string | null; cancel_by?: string; days_left?: number; expired?: boolean }

export function useTerms() {
  return useQuery({ queryKey: ['contract-terms'], queryFn: () => api<{ items: Term[] }>('/contract-terms') })
}

function useRefreshTerms() {
  const client = useQueryClient()
  return () => { client.invalidateQueries({ queryKey: ['contract-terms'] }); client.invalidateQueries({ queryKey: ['upcoming'] }); client.invalidateQueries({ queryKey: ['attention'] }) }
}

function downloadIcs(t: Term) {
  if (!t.cancel_by) return
  const blob = new Blob([deadlineIcs(t.name, t.cancel_by, t.key.replace(/[^a-z0-9]/gi, '').slice(0, 40) || 'vertrag')], { type: 'text/calendar' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = `kuendigen-${t.name.replace(/[^\p{L}\p{N}]+/gu, '-').slice(0, 40)}.ics`; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function CancelledBadge({ t }: { t: Term }) {
  const { language } = useLocale(); const de = language === 'de'
  return <Badge tone={t.ended ? '' : 'success'}>{t.term_end ? (de ? `gekündigt zum ${formatDate(t.term_end, language)}` : `cancelled, ends ${formatDate(t.term_end, language)}`) : (de ? 'gekündigt' : 'cancelled')}</Badge>
}

/** Deadlines panel for the contracts page: next chance to cancel per contract with stored terms. */
export function DeadlinePanel() {
  const { language } = useLocale(); const de = language === 'de'
  const terms = useTerms()
  const [letter, setLetter] = useState<Term | null>(null)
  const items = terms.data?.items ?? []
  if (!items.length) return null
  const tone = (t: Term) => t.expired ? '' : (t.days_left ?? 999) <= 14 ? 'danger' : (t.days_left ?? 999) <= 45 ? 'warning' : 'success'
  return <Panel title={de ? 'Kündigungsfristen' : 'Cancellation deadlines'} action={<AlarmClock size={18} />} description={de ? 'Bis wann du spätestens kündigen musst, damit sich der Vertrag nicht verlängert. FinSight erinnert dich 14, 7 und 2 Tage vorher.' : 'The last day to cancel before the contract renews. FinSight reminds you 14, 7 and 2 days before.'}>
    <DataTable headers={[de ? 'Vertrag' : 'Contract', de ? 'Kündigen bis' : 'Cancel by', de ? 'Laufzeit bis' : 'Term ends', de ? 'Kosten/Jahr' : 'Cost/year', '', '']}>
      {items.map(t => <tr key={t.key}><td>{t.name}{t.note && <div className="small muted">{t.note}</div>}</td>
        <td className="nowrap">{t.cancel_by ? formatDate(t.cancel_by, language) : '—'}</td>
        <td className="nowrap small">{t.term_end ? formatDate(t.term_end, language) : '—'}{!t.cancelled && t.renew_months ? <div className="muted">{de ? `verlängert sich um ${t.renew_months} Mon.` : `renews ${t.renew_months} mo.`}</div> : null}</td>
        <td>{t.annual_cost ? <Money value={t.annual_cost} /> : '—'}</td>
        <td>{t.cancelled ? <CancelledBadge t={t} /> : <Badge tone={tone(t)}>{t.expired ? (de ? 'abgelaufen' : 'ended') : de ? `noch ${t.days_left} Tage` : `${t.days_left} days left`}</Badge>}</td>
        <td className="nowrap">{!t.cancelled && <>
          <Button variant="ghost" onClick={() => setLetter(t)}><FileSignature size={15} />{de ? 'Kündigen' : 'Cancel'}</Button>
          {t.cancel_by && <Button variant="ghost" aria-label={de ? `Frist ${t.name} in den Kalender` : `Add ${t.name} deadline to calendar`} onClick={() => downloadIcs(t)}><CalendarPlus size={15} /></Button>}
        </>}</td></tr>)}
    </DataTable>
    {letter && <CancelDialog term={letter} onClose={() => setLetter(null)} />}
  </Panel>
}

const SENDER_KEY = 'finsight.cancel.sender'
function loadSender(): Sender {
  try { const raw = JSON.parse(localStorage.getItem(SENDER_KEY) ?? '{}'); return { name: String(raw.name ?? ''), address: String(raw.address ?? ''), city: String(raw.city ?? '') } }
  catch { return { name: '', address: '', city: '' } }
}

function printText(title: string, text: string) {
  const frame = document.createElement('iframe')
  frame.style.position = 'fixed'; frame.style.width = '0'; frame.style.height = '0'; frame.style.border = '0'
  document.body.appendChild(frame)
  const doc = frame.contentDocument
  if (!doc) return
  doc.title = title
  const pre = doc.createElement('pre')
  pre.textContent = text
  pre.style.cssText = 'font: 11pt/1.5 Georgia, serif; white-space: pre-wrap; margin: 25mm 20mm;'
  doc.body.appendChild(pre)
  frame.contentWindow?.print()
  setTimeout(() => frame.remove(), 1000)
}

/** Letter generator: everything stays in the browser; marking as cancelled freezes the end date and stops reminders. */
export function CancelDialog({ term, onClose }: { term: Term; onClose: () => void }) {
  const { language } = useLocale(); const de = language === 'de'
  const refresh = useRefreshTerms()
  const [sender, setSender] = useState<Sender>(loadSender)
  const [provider, setProvider] = useState(term.name)
  const [providerAddress, setProviderAddress] = useState('')
  const [customer, setCustomer] = useState(term.customer_number ?? '')
  const [copied, setCopied] = useState(false)
  useEffect(() => { try { localStorage.setItem(SENDER_KEY, JSON.stringify(sender)) } catch { /* private mode */ } }, [sender])
  const generated = useMemo(() => cancelLetter({ sender, provider, providerAddress, contract: term.name, customerNumber: customer, termEnd: term.term_end, today: new Date() }),
    [sender, provider, providerAddress, customer, term.name, term.term_end])
  const [text, setText] = useState<string | null>(null)
  useEffect(() => setText(null), [generated])
  const letter = text ?? generated
  const mark = useMutation({
    mutationFn: async () => {
      if (customer !== (term.customer_number ?? '') && 'configured_term_end' in term)
        await send(`/contract-terms?key=${encodeURIComponent(term.key)}`, { term_end: term.configured_term_end ?? null, notice_days: term.notice_days, renew_months: term.renew_months, note: term.note, customer_number: customer }, 'PUT')
      return send<Term>(`/contract-terms/cancel?key=${encodeURIComponent(term.key)}`, {})
    },
    onSuccess: () => { refresh(); onClose() },
  })
  const copy = async () => { try { await navigator.clipboard.writeText(letter); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch { setCopied(false) } }
  return <Dialog title={de ? `Kündigung: ${term.name}` : `Cancel: ${term.name}`} onClose={onClose}>
    <div className="form-stack">
      <Notice>{de
        ? `${term.term_end ? `Der Brief kündigt zum ${formatDate(term.term_end, language)}` : 'Der Brief kündigt zum nächstmöglichen Zeitpunkt'}${term.cancel_by ? `; er muss bis ${formatDate(term.cancel_by, language)} beim Anbieter sein` : ''}. Schick ihn so, dass du den Zugang nachweisen kannst (E-Mail mit Bestätigung, Einschreiben, Kündigungsbutton auf der Website). Nichts davon verlässt FinSight automatisch.`
        : `${term.term_end ? `Cancels as of ${formatDate(term.term_end, language)}` : 'Cancels at the next possible date'}${term.cancel_by ? `; it must reach the provider by ${formatDate(term.cancel_by, language)}` : ''}. Send it in a way you can prove. FinSight sends nothing itself.`}</Notice>
      <div className="form-grid">
        <Field label={de ? 'Dein Name' : 'Your name'}><input autoComplete="name" maxLength={120} value={sender.name} onChange={e => setSender({ ...sender, name: e.target.value })} /></Field>
        <Field label={de ? 'Ort (für das Datum)' : 'City'}><input autoComplete="address-level2" maxLength={80} value={sender.city} onChange={e => setSender({ ...sender, city: e.target.value })} /></Field>
        <Field label={de ? 'Deine Anschrift' : 'Your address'} hint={de ? 'Bleibt nur in diesem Browser gespeichert.' : 'Stored only in this browser.'}><textarea rows={2} autoComplete="street-address" maxLength={300} value={sender.address} onChange={e => setSender({ ...sender, address: e.target.value })} /></Field>
        <Field label={de ? 'Kundennummer / Vertragsnummer' : 'Customer number'}><input maxLength={120} value={customer} onChange={e => setCustomer(e.target.value)} /></Field>
        <Field label={de ? 'Anbieter' : 'Provider'}><input maxLength={200} value={provider} onChange={e => setProvider(e.target.value)} /></Field>
        <Field label={de ? 'Anschrift des Anbieters' : 'Provider address'}><textarea rows={2} maxLength={300} value={providerAddress} onChange={e => setProviderAddress(e.target.value)} /></Field>
      </div>
      <Field label={de ? 'Kündigungsschreiben (anpassbar)' : 'Letter (editable)'}><textarea className="letter-text" rows={16} value={letter} onChange={e => setText(e.target.value)} /></Field>
      <Feedback error={mark.error} />
      <div className="form-actions">
        <Button type="button" variant="outline" onClick={copy}><Copy size={15} />{copied ? (de ? 'Kopiert' : 'Copied') : (de ? 'Kopieren' : 'Copy')}</Button>
        <Button type="button" variant="outline" onClick={() => printText(`Kündigung ${term.name}`, letter)}><Printer size={15} />{de ? 'Drucken / PDF' : 'Print / PDF'}</Button>
        <Button type="button" busy={mark.isPending} onClick={() => mark.mutate()}>{de ? 'Abgeschickt – als gekündigt markieren' : 'Sent – mark as cancelled'}</Button>
      </div>
    </div>
  </Dialog>
}

/** Form inside the contract detail dialog. */
export function TermForm({ contractKey, name }: { contractKey: string; name?: string }) {
  const { language } = useLocale(); const de = language === 'de'
  const refresh = useRefreshTerms()
  const terms = useTerms()
  const current = terms.data?.items.find(t => t.key === contractKey)
  const [letter, setLetter] = useState(false)
  const [form, setForm] = useState<{ term_end: string; notice_days: string; renew_months: string; note: string; customer_number: string } | null>(null)
  const value = form ?? { term_end: current?.configured_term_end ?? '', notice_days: String(current?.notice_days ?? 30), renew_months: String(current?.renew_months ?? 12), note: current?.note ?? '', customer_number: current?.customer_number ?? '' }
  const done = () => { refresh(); setForm(null) }
  const save = useMutation({ mutationFn: () => send(`/contract-terms?key=${encodeURIComponent(contractKey)}`, { term_end: value.term_end || null, notice_days: Number(value.notice_days) || 0, renew_months: Number(value.renew_months) || 0, note: value.note, customer_number: value.customer_number }, 'PUT'), onSuccess: done })
  const remove = useMutation({ mutationFn: () => send(`/contract-terms?key=${encodeURIComponent(contractKey)}`, undefined, 'DELETE'), onSuccess: done })
  const undo = useMutation({ mutationFn: () => send(`/contract-terms/cancel?key=${encodeURIComponent(contractKey)}`, undefined, 'DELETE'), onSuccess: done })
  const letterTerm: Term = current ?? { key: contractKey, name: name ?? contractKey, status: 'unknown', notice_days: Number(value.notice_days) || 30, renew_months: Number(value.renew_months) || 0, note: '', customer_number: value.customer_number }
  return <><form className="form-stack term-form" onSubmit={e => { e.preventDefault(); save.mutate() }}>
    <h3>{de ? 'Laufzeit & Kündigung' : 'Term & cancellation'}</h3>
    {current?.cancelled ? <p className="small"><CancelledBadge t={current} /> {current.cancelled_on && <span className="muted">{de ? `abgeschickt am ${formatDate(current.cancelled_on, language)}` : `sent ${formatDate(current.cancelled_on, language)}`}</span>}</p>
      : current?.cancel_by && <p className="small">{de ? 'Nächste Kündigungsmöglichkeit' : 'Next chance to cancel'}: <strong>{formatDate(current.cancel_by, language)}</strong></p>}
    <div className="form-grid">
      <Field label={de ? 'Laufzeit endet am' : 'Term ends on'}><input type="date" value={value.term_end} onChange={e => setForm({ ...value, term_end: e.target.value })} /></Field>
      <Field label={de ? 'Kündigungsfrist (Tage)' : 'Notice (days)'}><input type="number" min={0} max={730} value={value.notice_days} onChange={e => setForm({ ...value, notice_days: e.target.value })} /></Field>
      <Field label={de ? 'Verlängert sich um (Monate, 0 = nicht)' : 'Renews by (months, 0 = no)'}><input type="number" min={0} max={120} value={value.renew_months} onChange={e => setForm({ ...value, renew_months: e.target.value })} /></Field>
      <Field label={de ? 'Kundennummer' : 'Customer number'}><input maxLength={120} value={value.customer_number} onChange={e => setForm({ ...value, customer_number: e.target.value })} /></Field>
      <Field label={de ? 'Notiz' : 'Note'}><input maxLength={300} value={value.note} onChange={e => setForm({ ...value, note: e.target.value })} /></Field>
    </div>
    <Feedback error={save.error || remove.error || undo.error} />
    <div className="form-actions">
      {current && !current.cancelled && <Button type="button" variant="ghost" onClick={() => remove.mutate()}>{de ? 'Frist entfernen' : 'Remove'}</Button>}
      {current?.cancelled ? <Button type="button" variant="ghost" busy={undo.isPending} onClick={() => undo.mutate()}><Undo2 size={15} />{de ? 'Kündigung zurücknehmen' : 'Undo cancellation'}</Button>
        : <Button type="button" variant="outline" onClick={() => setLetter(true)}><FileSignature size={15} />{de ? 'Kündigungsschreiben' : 'Cancellation letter'}</Button>}
      {current?.cancel_by && !current.cancelled && <Button type="button" variant="outline" onClick={() => downloadIcs(current)}><CalendarPlus size={15} />{de ? 'In den Kalender' : 'Add to calendar'}</Button>}
      <Button busy={save.isPending}>{de ? 'Frist speichern' : 'Save term'}</Button>
    </div>
  </form>
  {letter && <CancelDialog term={letterTerm} onClose={() => setLetter(false)} />}</>
}
