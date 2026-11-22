import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, Wallet } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { Button, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Entry = { id: string; day: string; amount: string; category: string; merchant: string; note: string }
type Data = { wallet: { enabled: boolean; since?: string; withdrawn?: string; logged?: string; in_wallet?: string }; entries: Entry[] }
const QUICK = ['Lebensmittel', 'Restaurants', 'Bäcker', 'Getränke', 'Freizeit', 'Trinkgeld', 'Sonstiges']

export default function CashPage() {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['cashbook'], queryFn: () => api<Data>('/cashbook') })
  const cats = useQuery({ queryKey: ['plan', 'categories'], queryFn: () => api<{ categories: string[] }>('/plan?history=1') })
  const today = new Date().toISOString().slice(0, 10)
  const [start, setStart] = useState(today.slice(0, 8) + '01')
  const [form, setForm] = useState({ amount: '', category: 'Lebensmittel', merchant: '', day: today })
  const refresh = () => { client.invalidateQueries({ queryKey: ['cashbook'] }); client.invalidateQueries({ queryKey: ['overview'] }); client.invalidateQueries({ queryKey: ['plan'] }) }
  const enable = useMutation({ mutationFn: (since: string | null) => send('/cashbook/settings', { since }, 'PUT'), onSuccess: refresh })
  const add = useMutation({ mutationFn: () => send('/cashbook/entries', { amount: form.amount.replace(',', '.'), category: form.category, merchant: form.merchant, day: form.day }), onSuccess: () => { setForm({ ...form, amount: '', merchant: '' }); refresh() } })
  const remove = useMutation({ mutationFn: (id: string) => send(`/cashbook/entries/${encodeURIComponent(id)}`, undefined, 'DELETE'), onSuccess: refresh })
  const d = query.data
  const options = [...new Set([...QUICK, ...(cats.data?.categories ?? [])])]
  return <>
    <PageHeader title={de ? 'Bargeld' : 'Cash'} description={de ? 'Trag ein, wofür du Bargeld ausgibst. Abhebungen am Automaten zählen dann nicht mehr als Ausgabe, sondern nur deine Einträge – nichts wird doppelt gezählt.' : 'Log what you spend in cash. ATM withdrawals then stop counting as spending; only your entries count.'} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{d && (!d.wallet.enabled ? <Panel title={de ? 'Haushaltsbuch starten' : 'Start the cash book'} action={<Wallet size={18} />}>
      <p>{de ? 'Ab dem Startdatum werden Bargeld-Abhebungen als Umbuchung ins Portemonnaie behandelt. Davor bleibt alles, wie es ist.' : 'From the start date, cash withdrawals count as moving money into your wallet. Earlier months stay as they are.'}</p>
      <div className="form-grid"><Field label={de ? 'Startdatum' : 'Start date'}><input id="cash-start" type="date" value={start} max={today} onChange={e => setStart(e.target.value)} /></Field>
        <div><Button busy={enable.isPending} onClick={() => enable.mutate(start)}>{de ? 'Starten' : 'Start'}</Button></div></div>
      <Feedback error={enable.error} />
    </Panel> : <>
      <div className="stat-grid">
        <div className="detail-stat"><span>{de ? 'Im Portemonnaie (rechnerisch)' : 'In wallet (calculated)'}</span><strong><Money value={d.wallet.in_wallet} /></strong></div>
        <div className="detail-stat"><span>{de ? 'Abgehoben' : 'Withdrawn'}</span><Money value={d.wallet.withdrawn} /><small className="muted">{de ? 'seit' : 'since'} {formatDate(d.wallet.since, language)}</small></div>
        <div className="detail-stat"><span>{de ? 'Erfasst' : 'Logged'}</span><Money value={d.wallet.logged} /></div>
      </div>
      {Number(d.wallet.in_wallet) < 0 && <Notice warning>{de ? 'Mehr erfasst als abgehoben – vielleicht hattest du schon Bargeld vor dem Startdatum.' : 'More logged than withdrawn – maybe you had cash before the start date.'}</Notice>}
      <Panel title={de ? 'Barausgabe eintragen' : 'Log cash spending'}>
        <form className="cash-form" onSubmit={e => { e.preventDefault(); add.mutate() }}>
          <Field label={de ? 'Betrag (€)' : 'Amount (€)'}><input id="cash-amount" aria-label={de ? "Betrag in Euro" : "Amount in euro"} className="cash-amount" required inputMode="decimal" pattern="[0-9]+([.,][0-9]{1,2})?" placeholder="0,00" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></Field>
          <div className="chip-row" role="group" aria-label={de ? 'Kategorie schnell wählen' : 'Quick category'}>{QUICK.map(c => <button type="button" key={c} className={`chip chip-button ${form.category === c ? 'active' : ''}`} aria-pressed={form.category === c} onClick={() => setForm({ ...form, category: c })}>{c}</button>)}</div>
          <div className="form-grid">
            <Field label={de ? 'Kategorie' : 'Category'}><input id="cash-category" list="cash-categories" required maxLength={120} value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} /><datalist id="cash-categories">{options.map(c => <option key={c} value={c} />)}</datalist></Field>
            <Field label={de ? 'Wo (optional)' : 'Where (optional)'}><input id="cash-merchant" maxLength={200} value={form.merchant} onChange={e => setForm({ ...form, merchant: e.target.value })} /></Field>
            <Field label={de ? 'Datum' : 'Date'}><input id="cash-day" type="date" max={today} value={form.day} onChange={e => setForm({ ...form, day: e.target.value })} /></Field>
          </div>
          <Feedback error={add.error} />
          <Button busy={add.isPending}>{de ? 'Eintragen' : 'Log'}</Button>
        </form>
      </Panel>
      <Panel title={de ? 'Einträge' : 'Entries'}>
        {!d.entries.length ? <p className="muted">{de ? 'Noch keine Einträge.' : 'No entries yet.'}</p> :
          <ul className="open-list">{d.entries.map(e => <li key={e.id}><div className="open-head"><span><strong>{e.category}</strong>{e.merchant && <span className="muted"> · {e.merchant}</span>}</span><span className="badge-row"><Money value={e.amount} /><Button variant="ghost" aria-label={de ? 'Eintrag löschen' : 'Delete entry'} onClick={() => remove.mutate(e.id)}><Trash2 size={14} /></Button></span></div><div className="small muted">{formatDate(e.day, language)}</div></li>)}</ul>}
        <Feedback error={remove.error} />
      </Panel>
      <p className="small"><button type="button" className="link-button" onClick={() => enable.mutate(null)}>{de ? 'Haushaltsbuch beenden (Abhebungen zählen wieder als Ausgabe)' : 'Stop the cash book'}</button></p>
    </>)}</QueryState>
  </>
}
