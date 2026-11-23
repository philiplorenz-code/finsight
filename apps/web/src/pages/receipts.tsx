import { usePaperless } from '../components/paperless'
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Camera, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Item = { id?: string; name: string; quantity: string; unit_price?: string | null; total: string; category: string }
type Receipt = { id: string; status: string; merchant?: string | null; receipt_date?: string | null; total?: string | null; transaction_id?: string | null; paperless_sent_at?: string | null; items: Item[]; items_total: string; difference?: string | null; created_at: string }
type Stats = { months: string[]; receipts: number; total: string; categories: { category: string; total: string }[]; top_items: { name: string; count: number; total: string; price_first?: string | null; price_last?: string | null }[] }

const STATUS: Record<string, [string, string, string]> = {
  uploaded: ['Hochgeladen', 'Uploaded', ''], extracted: ['Ausgelesen – bitte prüfen', 'Extracted – please review', 'warning'],
  extraction_failed: ['Nicht lesbar – manuell erfassen', 'Unreadable – enter manually', 'danger'], reviewed: ['Geprüft', 'Reviewed', 'success'],
}

async function uploadFile(file: File) {
  const body = new FormData(); body.append('file', file)
  return api<Receipt>('/receipts', { method: 'POST', body })
}

export default function ReceiptsPage() {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [editing, setEditing] = useState<Receipt | null>(null)
  const list = useQuery({ queryKey: ['receipts'], queryFn: () => api<{ items: Receipt[]; categories: string[] }>('/receipts') })
  const stats = useQuery({ queryKey: ['receipt-stats'], queryFn: () => api<Stats>('/receipts/stats?months=6') })
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<{ ai?: { enabled?: boolean; external_consent?: boolean } }>('/settings') })
  const aiReady = !!settings.data?.ai?.enabled && !!settings.data?.ai?.external_consent
  const refresh = () => { client.invalidateQueries({ queryKey: ['receipts'] }); client.invalidateQueries({ queryKey: ['receipt-stats'] }) }
  const upload = useMutation({ mutationFn: uploadFile, onSuccess: r => { refresh(); setEditing(r) } })
  const extract = useMutation({ mutationFn: (id: string) => send<Receipt>(`/receipts/${encodeURIComponent(id)}/extract`), onSuccess: r => { refresh(); setEditing(r) } })
  const paperless = usePaperless()
  const archive = useMutation({ mutationFn: (id: string) => send<Receipt>(`/receipts/${encodeURIComponent(id)}/paperless`), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: string) => send(`/receipts/${encodeURIComponent(id)}`, undefined, 'DELETE'), onSuccess: refresh })
  const max = Math.max(1, ...(stats.data?.categories ?? []).map(c => Number(c.total)))
  return <>
    <PageHeader title={de ? 'Kassenzettel' : 'Receipts'} description={de ? 'Fotografiere deine Kassenzettel – jede Position landet in der Auswertung, damit du genau siehst, wofür dein Lebensmittel-Geld draufgeht.' : 'Photograph your receipts – every line item is analysed so you see exactly where your grocery money goes.'}
      action={<><input ref={input} type="file" accept="image/*" capture="environment" hidden onChange={e => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }} />
        <Button busy={upload.isPending} onClick={() => input.current?.click()}><Camera size={17} />{de ? 'Kassenzettel fotografieren' : 'Photograph receipt'}</Button></>} />
    <Feedback error={upload.error || extract.error || remove.error || archive.error} />
    {aiReady ? <Notice>{de ? '„Mit KI auslesen“ sendet das Foto an den in den Einstellungen gewählten KI-Anbieter (Budget und Einwilligung wie beim Analysten). Das Modell muss Bilder verstehen. Ohne KI kannst du die Positionen selbst eintragen.' : '“Read with AI” sends the photo to the AI provider chosen in settings (same budget and consent as the analyst). The model must support images. Without AI you can enter items yourself.'}</Notice> : <Notice>{de ? 'Nach dem Foto öffnet sich der Editor: Händler, Datum, Summe und Positionen eintragen. Die Kategorien landen direkt in der Auswertung. Auslesen per KI lässt sich später in den Einstellungen aktivieren (bildfähiges Modell nötig).' : 'After the photo the editor opens: enter merchant, date, total and items. AI reading can be enabled later in settings (image-capable model required).'}</Notice>}
    {!!stats.data?.categories.length && <Panel title={de ? 'Wofür dein Einkauf draufgeht (6 Monate)' : 'Where your shopping goes (6 months)'} description={`${stats.data.receipts} ${de ? 'Kassenzettel' : 'receipts'} · ${de ? 'zusammen' : 'together'}`} action={<Money value={stats.data.total} />}>
      <div className="item-bars">{stats.data.categories.map(c => <div key={c.category} className="item-bar"><span className="item-bar-label">{c.category}</span><span className="item-bar-track"><span style={{ width: `${Math.max(2, Number(c.total) / max * 100)}%` }} /></span><Money value={c.total} /></div>)}</div>
      <h3>{de ? 'Teuerste Artikel' : 'Top items'}</h3>
      <DataTable headers={[de ? 'Artikel' : 'Item', de ? 'Käufe' : 'Purchases', de ? 'Summe' : 'Total', de ? 'Preis vorher → jetzt' : 'Price before → now']}>
        {stats.data.top_items.slice(0, 10).map(i => <tr key={i.name}><td>{i.name}</td><td>{i.count}</td><td><Money value={i.total} /></td><td className="small">{i.price_first && i.price_last ? <><Money value={i.price_first} /> → <Money value={i.price_last} className={Number(i.price_last) > Number(i.price_first) ? 'negative' : ''} /></> : '—'}</td></tr>)}
      </DataTable>
    </Panel>}
    <Panel title={de ? 'Deine Kassenzettel' : 'Your receipts'}>
      <QueryState pending={list.isPending} error={list.error} retry={list.refetch} empty={!list.data?.items.length}>
        <div className="receipt-grid">{list.data?.items.map(r => { const [sde, sen, tone] = STATUS[r.status] ?? [r.status, r.status, '']; return <article key={r.id} className="receipt-card">
          <img src={`/api/receipts/${encodeURIComponent(r.id)}/image`} alt={de ? 'Kassenzettel' : 'Receipt'} loading="lazy" />
          <div className="receipt-body">
            <strong>{r.merchant || (de ? 'Unbekannter Händler' : 'Unknown merchant')}</strong>
            <span className="muted small">{r.receipt_date ? formatDate(r.receipt_date, language) : '—'} · {r.items.length} {de ? 'Positionen' : 'items'}</span>
            <Money value={r.total ?? r.items_total} />
            <span className="badge-row"><Badge tone={tone}>{de ? sde : sen}</Badge>{r.transaction_id ? <Badge tone="success">{de ? 'Buchung gefunden' : 'Booking matched'}</Badge> : r.total ? <Badge>{de ? 'keine Buchung' : 'no booking'}</Badge> : null}</span>
            <span className="badge-row">
              {aiReady && r.status !== 'reviewed' && <Button variant="outline" busy={extract.isPending && extract.variables === r.id} onClick={() => extract.mutate(r.id)}><Sparkles size={15} />{de ? 'Mit KI auslesen' : 'Read with AI'}</Button>}
              {paperless.data?.reachable && (r.paperless_sent_at ? <span className="small muted">{de ? 'In Paperless' : 'In Paperless'} ✓</span> : <Button variant="outline" busy={archive.isPending && archive.variables === r.id} onClick={() => archive.mutate(r.id)}><Archive size={15} />{de ? 'In Paperless ablegen' : 'Archive in Paperless'}</Button>)}
              <Button variant="ghost" aria-label={`${de ? 'Bearbeiten' : 'Edit'}: ${r.merchant ?? r.id}`} onClick={() => setEditing(r)}><Pencil size={15} /></Button>
              <Button variant="ghost" aria-label={de ? 'Löschen' : 'Delete'} onClick={() => remove.mutate(r.id)}><Trash2 size={15} /></Button>
            </span>
          </div>
        </article> })}</div>
      </QueryState>
    </Panel>
    {editing && <ReceiptEditor receipt={editing} categories={list.data?.categories ?? []} onClose={() => setEditing(null)} onSaved={refresh} />}
  </>
}

function ReceiptEditor({ receipt, categories, onClose, onSaved }: { receipt: Receipt; categories: string[]; onClose: () => void; onSaved: () => void }) {
  const { language } = useLocale(); const de = language === 'de'
  const [head, setHead] = useState({ merchant: receipt.merchant ?? '', receipt_date: receipt.receipt_date ?? '', total: receipt.total ? String(Number(receipt.total)) : '' })
  const [items, setItems] = useState<Item[]>(receipt.items.map(i => ({ ...i, quantity: String(Number(i.quantity)), total: String(Number(i.total)), unit_price: i.unit_price ? String(Number(i.unit_price)) : '' })))
  const save = useMutation({
    mutationFn: () => send(`/receipts/${encodeURIComponent(receipt.id)}`, { merchant: head.merchant || null, receipt_date: head.receipt_date || null, total: head.total || null,
      items: items.filter(i => i.name.trim() && i.total !== '').map(i => ({ name: i.name, quantity: i.quantity || '1', unit_price: i.unit_price || null, total: i.total, category: i.category })) }, 'PATCH'),
    onSuccess: () => { onSaved(); onClose() },
  })
  const sum = items.reduce((s, i) => s + (Number(i.total) || 0), 0)
  const set = (idx: number, patch: Partial<Item>) => setItems(items.map((i, n) => n === idx ? { ...i, ...patch } : i))
  return <Dialog title={de ? 'Kassenzettel prüfen' : 'Review receipt'} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate() }}>
      <div className="receipt-editor-top">
        <img src={`/api/receipts/${encodeURIComponent(receipt.id)}/image`} alt={de ? 'Kassenzettel' : 'Receipt'} />
        <div className="form-stack">
          <Field label={de ? 'Händler' : 'Merchant'}><input maxLength={200} value={head.merchant} onChange={e => setHead({ ...head, merchant: e.target.value })} /></Field>
          <Field label={de ? 'Datum' : 'Date'}><input type="date" value={head.receipt_date} onChange={e => setHead({ ...head, receipt_date: e.target.value })} /></Field>
          <Field label={de ? 'Summe laut Bon (€)' : 'Receipt total (€)'}><input type="number" step="0.01" min="0" value={head.total} onChange={e => setHead({ ...head, total: e.target.value })} /></Field>
          <p className={`small ${head.total && Math.abs(Number(head.total) - sum) > 0.009 ? 'negative' : 'muted'}`}>{de ? 'Summe der Positionen' : 'Sum of items'}: {sum.toLocaleString(de ? 'de-DE' : 'en-GB', { style: 'currency', currency: 'EUR' })}</p>
        </div>
      </div>
      <div className="table-scroll"><table className="data-table receipt-items"><thead><tr><th>{de ? 'Artikel' : 'Item'}</th><th>{de ? 'Menge' : 'Qty'}</th><th>{de ? 'Einzelpreis' : 'Unit'}</th><th>{de ? 'Summe' : 'Total'}</th><th>{de ? 'Kategorie' : 'Category'}</th><th /></tr></thead>
        <tbody>{items.map((i, n) => <tr key={n}>
          <td><input aria-label={de ? 'Artikel' : 'Item'} maxLength={200} value={i.name} onChange={e => set(n, { name: e.target.value })} /></td>
          <td><input aria-label={de ? 'Menge' : 'Quantity'} type="number" step="0.001" value={i.quantity} onChange={e => set(n, { quantity: e.target.value })} /></td>
          <td><input aria-label={de ? 'Einzelpreis' : 'Unit price'} type="number" step="0.01" value={i.unit_price ?? ''} onChange={e => set(n, { unit_price: e.target.value })} /></td>
          <td><input aria-label={de ? 'Summe' : 'Total'} type="number" step="0.01" value={i.total} onChange={e => set(n, { total: e.target.value })} /></td>
          <td><select aria-label={de ? 'Kategorie' : 'Category'} value={i.category} onChange={e => set(n, { category: e.target.value })}>{categories.map(c => <option key={c} value={c}>{c}</option>)}</select></td>
          <td><Button type="button" variant="ghost" aria-label={de ? 'Position entfernen' : 'Remove item'} onClick={() => setItems(items.filter((_, k) => k !== n))}><Trash2 size={14} /></Button></td>
        </tr>)}</tbody></table></div>
      <Button type="button" variant="outline" onClick={() => setItems([...items, { name: '', quantity: '1', unit_price: '', total: '', category: 'Sonstiges' }])}><Plus size={15} />{de ? 'Position hinzufügen' : 'Add item'}</Button>
      <Feedback error={save.error} />
      <div className="form-actions"><Button type="button" variant="outline" onClick={onClose}>{de ? 'Abbrechen' : 'Cancel'}</Button><Button busy={save.isPending}>{de ? 'Speichern' : 'Save'}</Button></div>
    </form>
  </Dialog>
}
