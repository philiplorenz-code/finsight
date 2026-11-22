import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Search, X } from 'lucide-react'
import { api } from '../lib/api'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'

type Result = { transactions: { id: string; date: string; merchant: string; amount: string; category?: string; account?: string }[]
  merchants: { name: string; count: number }[]; contracts: { name: string; monthly: string; kind: string; status: string }[]
  accounts: { id: string; name: string; provider?: string | null }[] }

/** Search button for the top bar; Cmd/Ctrl+K opens it anywhere. */
export function GlobalSearch() {
  const { language } = useLocale(); const de = language === 'de'
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(t) }, [q])
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen(true) } if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key)
  }, [])
  const query = useQuery({ queryKey: ['search', debounced], queryFn: () => api<Result>(`/search?q=${encodeURIComponent(debounced)}`), enabled: open && debounced.length >= 2 })
  const go = (path: string) => { setOpen(false); setQ(''); navigate(path) }
  const r = query.data
  const empty = r && !r.transactions.length && !r.merchants.length && !r.contracts.length && !r.accounts.length
  return <>
    <button type="button" className="icon-button" aria-label={de ? 'Suchen' : 'Search'} title={de ? 'Suchen (⌘K)' : 'Search (⌘K)'} onClick={() => setOpen(true)}><Search size={19} /></button>
    {open && <div className="search-overlay" role="dialog" aria-modal="true" aria-label={de ? 'Suche' : 'Search'} onClick={() => setOpen(false)}>
      <div className="search-box" onClick={e => e.stopPropagation()}>
        <div className="search-input"><Search size={18} /><input ref={input} autoFocus enterKeyHint="search" value={q} onChange={e => setQ(e.target.value)} placeholder={de ? 'Händler, Buchung, Vertrag, Konto …' : 'Merchant, booking, contract, account…'} aria-label={de ? 'Suchbegriff' : 'Search term'} /><button type="button" className="icon-button" aria-label={de ? 'Schließen' : 'Close'} onClick={() => setOpen(false)}><X size={18} /></button></div>
        <div className="search-results">
          {debounced.length < 2 && <p className="muted small">{de ? 'Mindestens zwei Zeichen eingeben.' : 'Type at least two characters.'}</p>}
          {q.trim().length >= 2 && (q.trim() !== debounced || query.isFetching) && !r && <p className="muted small" role="status">{de ? 'Suche …' : 'Searching…'}</p>}
          {query.isError && <p className="muted small" role="alert">{de ? 'Suche gerade nicht möglich.' : 'Search unavailable.'}</p>}
          {empty && <p className="muted small">{de ? 'Nichts gefunden.' : 'Nothing found.'}</p>}
          {!!r?.merchants.length && <section><h4>{de ? 'Händler' : 'Merchants'}</h4>{r.merchants.map(m => <button type="button" key={m.name} onClick={() => go(`/transactions?search=${encodeURIComponent(m.name)}`)}><span>{m.name}</span><small className="muted">{m.count}×</small></button>)}</section>}
          {!!r?.transactions.length && <section><h4>{de ? 'Buchungen' : 'Bookings'}</h4>{r.transactions.map(t => <button type="button" key={t.id} onClick={() => go(`/transactions?detail=${encodeURIComponent(t.id)}`)}><span>{t.merchant}<small className="muted"> · {formatDate(t.date, language)} · {t.account}</small></span><span className="num">{formatMoney(t.amount, 'EUR', language)}</span></button>)}</section>}
          {!!r?.contracts.length && <section><h4>{de ? 'Verträge' : 'Contracts'}</h4>{r.contracts.map(c => <button type="button" key={c.name} onClick={() => go('/contracts')}><span>{c.name}</span><span className="num">{formatMoney(c.monthly, 'EUR', language)}/{de ? 'Mon.' : 'mo.'}</span></button>)}</section>}
          {!!r?.accounts.length && <section><h4>{de ? 'Konten' : 'Accounts'}</h4>{r.accounts.map(a => <button type="button" key={a.id} onClick={() => go('/accounts')}><span>{a.name}</span><small className="muted">{a.provider ?? ''}</small></button>)}</section>}
        </div>
      </div>
    </div>}
  </>
}
