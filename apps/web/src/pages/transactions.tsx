import { AccountSelect } from '../components/account-select'
import { MerchantProfile } from '../components/merchant-profile'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, ChevronLeft, ChevronRight, Search, SlidersHorizontal, Tags, Trash2 } from 'lucide-react'
import { api, items, queryString, send } from '../lib/api'
import type { Account, Transaction } from '../lib/types'
import { formatDate, useLocale } from '../lib/i18n'
import { localizeWarning } from '../lib/warnings'
import { Badge, Button, DataTable, Dialog, Feedback, Field, Money, Notice, PageHeader, QueryState } from '../components/ui'

type TransactionList = { items: Transaction[]; total?: number; page?: number; has_more?: boolean }
const aliases: Record<string, string> = { date_from: 'start', date_to: 'end', amount_min: 'min_amount', amount_max: 'max_amount', contract_id: 'contract' }
const views = ['all_transactions', 'included_spending', 'owned_liquid'] as const
export default function TransactionsPage() {
  const { t, language } = useLocale()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('search') || '')
  const [expanded, setExpanded] = useState(() => ['start', 'end', 'date_from', 'date_to', 'category', 'merchant', 'min_amount', 'max_amount', 'amount_min', 'amount_max', 'tag', 'contract', 'contract_id', 'is_transfer'].some(key => params.has(key)))
  const page = Math.max(1, Number(params.get('page') || 1))
  const selected = params.get('detail')
  const [merchant, setMerchant] = useState<string | null>(null)
  const update = (key: string, value: string) => setParams(p => {
    const next = new URLSearchParams(p)
    const canonical = aliases[key] || key
    Object.entries(aliases).forEach(([alias, target]) => { if (target === canonical) next.delete(alias) })
    value ? next.set(canonical, value) : next.delete(canonical)
    if (canonical !== 'page' && canonical !== 'detail') next.delete('page')
    return next
  })
  const filters = Object.fromEntries([...params].filter(([key]) => key !== 'detail' && !aliases[key]))
  Object.entries(aliases).forEach(([alias, canonical]) => { if (!params.has(canonical) && params.has(alias)) filters[canonical] = params.get(alias)! })
  const filterValue = (key: string) => filters[key] || ''
  const view = params.get('view') || 'all_transactions'
  const query = useQuery({ queryKey: ['transactions', params.toString().replace(/(&|^)detail=[^&]*/, '')], queryFn: () => api<TransactionList | Transaction[]>(`/transactions${queryString({ ...filters, page, page_size: 25 })}`) })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[] | { items: Account[] }>('/accounts') })
  const rows = items(query.data)
  const total = !Array.isArray(query.data) ? query.data?.total : undefined
  const hasMore = !Array.isArray(query.data) && query.data?.has_more !== undefined ? query.data.has_more : total !== undefined ? page * 25 < total : rows.length === 25
  return <><PageHeader title={t('transactions')} description={t('transactionsIntro')} action={<div className="header-actions"><CategoryRulesButton /><TransferCheck /></div>} /><div className="panel transaction-panel">
    <div className="transaction-toolbar"><form className="search-field" onSubmit={e => { e.preventDefault(); update('search', search) }}><Search size={17} /><input aria-label={t('search')} placeholder={language === 'de' ? 'Buchungen durchsuchen …' : 'Search transactions…'} value={search} onChange={e => setSearch(e.target.value)} /><Button variant="ghost" type="submit">{t('search')}</Button></form><AccountSelect accounts={items(accounts.data)} value={params.get('account_id') || ''} onChange={id => update('account_id', id)} anyLabel={`${t('all')} · ${t('accounts')}`} label={t('account')} /><Button variant="outline" onClick={() => setExpanded(e => !e)} aria-expanded={expanded}><SlidersHorizontal size={16} />Filter</Button></div>
    <div className="filter-grid">
      <Field label={language === 'de' ? 'Buchungsansicht' : 'Transaction view'}><select value={view} onChange={e => update('view', e.target.value)}>
        <option value="all_transactions">{language === 'de' ? 'Alle Buchungen' : 'All transactions'} · all_transactions</option>
        <option value="included_spending">{language === 'de' ? 'Einbezogene Ausgaben' : 'Included spending'} · included_spending</option>
        <option value="owned_liquid">{language === 'de' ? 'Eigene liquide Konten' : 'Owned liquid accounts'} · owned_liquid</option>
        {!views.some(value => value === view) && <option value={view}>{view}</option>}
      </select></Field>
      <Field label={t('currency')} hint={language === 'de' ? 'ISO-Code, z. B. EUR; leer = alle Währungen.' : 'ISO code, e.g. EUR; empty = all currencies.'}><input value={params.get('currency') || ''} maxLength={3} placeholder={t('all')} onChange={e => update('currency', e.target.value.toUpperCase())} /></Field>
    </div>
    {expanded && <div className="filter-grid">{[['start', 'from', 'date'], ['end', 'to', 'date'], ['category', 'category', 'text'], ['merchant', 'merchant', 'text'], ['min_amount', 'min', 'number'], ['max_amount', 'max', 'number'], ['tag', 'tags', 'text'], ['contract', 'contracts', 'text']].map(([key, label, type]) => <Field key={key} label={t(label as 'from')}><input type={type} step={type === 'number' ? '0.01' : undefined} value={filterValue(key)} onChange={e => update(key, e.target.value)} /></Field>)}<Field label={t('transfer')}><select value={params.get('is_transfer') || ''} onChange={e => update('is_transfer', e.target.value)}><option value="">{t('all')}</option><option value="true">{language === 'de' ? 'Nur Umbuchungen' : 'Only transfers'}</option><option value="false">{language === 'de' ? 'Ohne Umbuchungen' : 'Exclude transfers'}</option></select></Field></div>}
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!rows.length}><DataTable headers={[t('merchant'), t('date'), t('category'), t('account'), t('amount'), '']}>{rows.map(row => <tr key={row.id}><td><div className="transaction-name"><span className={`transaction-icon ${row.is_transfer ? 'transfer' : Number(row.amount) >= 0 ? 'positive' : ''}`}>{row.is_transfer ? <ArrowLeftRight size={17} /> : (row.merchant || row.counterparty || '?').slice(0, 1).toUpperCase()}</span><div>{row.merchant ? <button type="button" className="link-button" title={language === 'de' ? 'Händler-Profil öffnen' : 'Open merchant profile'} onClick={e => { e.stopPropagation(); setMerchant(row.merchant!) }}><strong>{row.merchant}</strong></button> : <strong>{row.counterparty || row.description || '—'}</strong>}<small>{row.description}</small>{row.pending && <Badge tone="warning">{t('pending')}</Badge>}</div></div></td><td className="nowrap muted">{formatDate(row.booking_date || row.date, language)}</td><td><Badge>{row.is_transfer ? t('transfer') : row.category || '—'}</Badge></td><td className="muted">{row.account_name || row.account_id || '—'}</td><td className="text-right"><Money value={row.amount} currency={row.currency} className={Number(row.amount) >= 0 ? 'positive-text' : ''} /></td><td><Button variant="ghost" aria-label={`${t('details')}: ${row.merchant || row.id}`} onClick={() => update('detail', row.id)}><ChevronRight size={18} /></Button></td></tr>)}</DataTable></QueryState><div className="pagination"><span>{t('page')} {page}{total !== undefined && <> · {total} {t('transactions')}</>}</span><div><Button variant="outline" disabled={page === 1 || query.isFetching} onClick={() => update('page', String(page - 1))}><ChevronLeft size={16} />{t('previous')}</Button><Button variant="outline" disabled={!hasMore || query.isFetching} onClick={() => update('page', String(page + 1))}>{t('next')}<ChevronRight size={16} /></Button></div></div></div>{selected && <TransactionDetail id={selected} onClose={() => update('detail', '')} />}{merchant && <MerchantProfile name={merchant} onClose={() => setMerchant(null)} />}</>
}
function TransactionDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { t, language } = useLocale(); const client = useQueryClient()
  const query = useQuery({ queryKey: ['transaction', id], queryFn: () => api<Transaction>(`/transactions/${encodeURIComponent(id)}`) })
  const [category, setCategory] = useState<string | null>(null)
  const [tags, setTags] = useState<string | null>(null)
  const mutation = useMutation({ mutationFn: (reset: boolean) => send(`/transactions/${encodeURIComponent(id)}${reset ? '/reset' : ''}`, reset ? undefined : { category_override: category ?? query.data?.effective_category ?? query.data?.category, tags: tags === null ? query.data?.tags || [] : tags.split(',').map(t => t.trim()).filter(Boolean) }, reset ? 'POST' : 'PATCH'), onSuccess: () => { client.invalidateQueries({ queryKey: ['transaction', id] }); client.invalidateQueries({ queryKey: ['transactions'] }); client.invalidateQueries({ queryKey: ['overview'] }); setCategory(null); setTags(null) } })
  return <Dialog title={t('details')} onClose={onClose}>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{query.data && <>
      <div className="transaction-detail-title"><h3>{query.data.merchant || query.data.counterparty || query.data.description}</h3><Money value={query.data.amount} currency={query.data.currency} /><p className="muted">{formatDate(query.data.booking_date || query.data.date, language)}</p>{query.data.is_transfer && <Badge>{t('transfer')}</Badge>}</div>
      {query.data.warnings?.map((w, i) => <Notice key={i} warning>{localizeWarning(w, language)}</Notice>)}
      <h3>{t('correction')}</h3><p className="muted small">{t('correctionText')}</p>
      <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate(false) }}>
        <Field label={t('category')}><input value={category ?? query.data.effective_category ?? query.data.category ?? ''} onChange={e => setCategory(e.target.value)} maxLength={120} /></Field>
        <Field label={t('tags')} hint={language === 'de' ? 'Mit Komma trennen.' : 'Separate with commas.'}><input value={tags ?? query.data.tags?.join(', ') ?? ''} onChange={e => setTags(e.target.value)} maxLength={1000} /></Field>
        <Feedback error={mutation.error} success={mutation.isSuccess} /><div className="form-actions"><Button variant="outline" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate(true)}>{t('reset')}</Button><Button busy={mutation.isPending}>{t('save')}</Button></div>
      </form><details className="source-details"><summary>{t('source')}</summary><pre>{JSON.stringify(query.data.source || {}, null, 2)}</pre></details>
      <RevisionDiffs id={id} />
    </>}</QueryState>
  </Dialog>
}

type Revision = { id: string; created_at: string; changes: { column: string; was: unknown; now: unknown }[] }
function RevisionDiffs({ id }: { id: string }) {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['transaction-revisions', id], queryFn: () => api<Revision[]>(`/transactions/${encodeURIComponent(id)}/revisions`) })
  if (!Array.isArray(query.data) || !query.data.length) return null
  const show = (v: unknown) => v == null || v === '' ? '—' : String(v)
  return <details className="source-details"><summary>{de ? `Frühere Fassungen aus Importen (${query.data.length})` : `Earlier versions from imports (${query.data.length})`}</summary>
    {query.data.map(r => <div key={r.id}><p className="muted small">{formatDate(r.created_at, language)}</p>
      <ul>{r.changes.map(c => <li key={c.column}><strong>{c.column}</strong>: {show(c.was)} → {show(c.now)}</li>)}</ul></div>)}
  </details>
}


type TransferResult = { pairs: number; newly_marked: number; newly_marked_inflow_total: string; applied: boolean }
function TransferCheck() {
  const { language } = useLocale()
  const de = language === 'de'
  const client = useQueryClient()
  const [result, setResult] = useState<TransferResult | null>(null)
  const [review, setReview] = useState(false)
  const run = useMutation({
    mutationFn: (dry: boolean) => send<TransferResult>(`/transfers/detect${dry ? '?dry_run=true' : ''}`),
    onSuccess: r => { setResult(r); if (r.applied) client.invalidateQueries() },
  })
  return <div className="transfer-check">
    <Button variant="outline" busy={run.isPending} onClick={() => run.mutate(true)}><ArrowLeftRight size={16} />{de ? 'Umbuchungen prüfen' : 'Check transfers'}</Button>
    <Button variant="ghost" onClick={() => setReview(true)}>{de ? 'Erkannte Paare ansehen' : 'Review pairs'}</Button>
    {review && <TransferReview de={de} onClose={() => setReview(false)} />}
    {result && <p className="muted">{result.applied
      ? (de ? `${result.newly_marked} Buchungen als Umbuchung markiert.` : `${result.newly_marked} bookings marked as transfers.`)
      : result.newly_marked === 0
        ? (de ? 'Keine neuen Umbuchungen gefunden.' : 'No new transfers found.')
        : <>{de ? `${result.pairs} Paare zwischen eigenen Konten gefunden, ${result.newly_marked} Buchungen würden als Umbuchung markiert (Eingänge: ` : `${result.pairs} pairs between own accounts, ${result.newly_marked} bookings would become transfers (inflows: `}<Money value={result.newly_marked_inflow_total} currency="EUR" />) <Button variant="ghost" busy={run.isPending} onClick={() => run.mutate(false)}>{de ? 'Anwenden' : 'Apply'}</Button></>}</p>}
    <Feedback error={run.error} />
  </div>
}


type CatRule = { id: string; name: string; category: string; pattern: string; match_field: string; flow: string; account_id: string | null; matches?: number }
function CategoryRulesButton() {
  const { language } = useLocale()
  const de = language === 'de'
  const [open, setOpen] = useState(false)
  return <><Button variant="outline" onClick={() => setOpen(true)}><Tags size={16} />{de ? 'Kategorie-Regeln' : 'Category rules'}</Button>{open && <CategoryRules de={de} onClose={() => setOpen(false)} />}</>
}
function CategoryRules({ de, onClose }: { de: boolean; onClose: () => void }) {
  const { t } = useLocale()
  const client = useQueryClient()
  const rulesQuery = useQuery({ queryKey: ['category-rules'], queryFn: () => api<CatRule[]>('/category-rules') })
  const empty = { name: '', category: '', pattern: '', match_field: 'any', flow: 'any' }
  const [form, setForm] = useState(empty)
  const done = () => { client.invalidateQueries({ queryKey: ['category-rules'] }); client.invalidateQueries() }
  const add = useMutation({ mutationFn: () => send('/category-rules', { ...form, position: rulesQuery.data?.length ?? 0 }), onSuccess: () => { setForm(empty); done() } })
  const remove = useMutation({ mutationFn: (id: string) => send(`/category-rules/${id}`, undefined, 'DELETE'), onSuccess: done })
  const flowName = (f: string) => f === 'income' ? (de ? 'Einnahmen' : 'income') : f === 'expense' ? (de ? 'Ausgaben' : 'expenses') : (de ? 'alle' : 'all')
  return <Dialog title={de ? 'Kategorie-Regeln' : 'Category rules'} onClose={onClose}>
    <p className="muted">{de ? 'Eine Regel weist passenden Buchungen eine Kategorie zu, ohne die importierten Daten zu ändern. Regeln gelten von oben nach unten (die erste passende gewinnt); eine manuelle Korrektur an einer Buchung hat immer Vorrang. Beispiel: Einnahmen von „Verlag“ als „Gewerbe-Einnahmen“.' : 'A rule assigns a category to matching bookings without changing imported data. First match wins; a manual correction on a booking always wins.'}</p>
    {rulesQuery.data?.length ? <ul>{rulesQuery.data.map(r => <li key={r.id}><strong>{r.name}</strong> → {r.category} <small className="muted">· „{r.pattern || '—'}“ · {flowName(r.flow)} · {r.matches ?? 0} {de ? 'Buchungen' : 'bookings'}</small> <Button variant="ghost" aria-label={`${t('delete')}: ${r.name}`} onClick={() => remove.mutate(r.id)}><Trash2 size={15} /></Button></li>)}</ul> : <p className="muted">{t('ruleNone')}</p>}
    <form className="form-stack" onSubmit={e => { e.preventDefault(); add.mutate() }}>
      <Field label={t('ruleName')}><input required maxLength={200} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
      <div className="form-grid">
        <Field label={t('ruleField')}><select value={form.match_field} onChange={e => setForm({ ...form, match_field: e.target.value })}>{[['any', 'ruleAny'], ['merchant', 'ruleMerchant'], ['description', 'ruleDescription']].map(([v, k]) => <option key={v} value={v}>{t(k as never)}</option>)}</select></Field>
        <Field label={t('rulePattern')} hint={t('rulePatternHint')}><input required maxLength={200} value={form.pattern} onChange={e => setForm({ ...form, pattern: e.target.value })} /></Field>
        <Field label={de ? 'Gilt für' : 'Applies to'}><select value={form.flow} onChange={e => setForm({ ...form, flow: e.target.value })}><option value="any">{de ? 'Einnahmen und Ausgaben' : 'Income and expenses'}</option><option value="income">{de ? 'Nur Einnahmen' : 'Income only'}</option><option value="expense">{de ? 'Nur Ausgaben' : 'Expenses only'}</option></select></Field>
        <Field label={de ? 'Neue Kategorie' : 'New category'}><input required maxLength={300} value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} /></Field>
      </div>
      <Feedback error={add.error || remove.error} />
      <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>{t('cancel')}</Button><Button type="submit" busy={add.isPending}>{t('ruleAdd')}</Button></div>
    </form>
  </Dialog>
}

type ReviewSide = { id: string; account: string; merchant: string; date: string; flagged_by_source: boolean }
type Review = { total: number; limit: number; pairs: { key: string; amount: string; currency: string; inflow: ReviewSide; outflow: ReviewSide }[]; rejections: { id: string; key: string; amount: string; currency: string; booking_date: string; label: string }[] }
function TransferReview({ de, onClose }: { de: boolean; onClose: () => void }) {
  const client = useQueryClient()
  const { language } = useLocale()
  const query = useQuery({ queryKey: ['transfer-review'], queryFn: () => api<Review>('/transfers/review') })
  const refresh = () => { client.invalidateQueries({ queryKey: ['transfer-review'] }); client.invalidateQueries() }
  const reject = useMutation({ mutationFn: (key: string) => send('/transfers/reject', { key }), onSuccess: refresh })
  const restore = useMutation({ mutationFn: (id: string) => send(`/transfers/rejections/${id}`, undefined, 'DELETE'), onSuccess: refresh })
  const data = query.data
  return <Dialog title={de ? 'Erkannte Umbuchungen prüfen' : 'Review detected transfers'} onClose={onClose}>
    <p className="muted">{de ? 'Diese Paare hat FinSight selbst als Umbuchung erkannt (gleicher Betrag, höchstens 3 Tage Abstand, zwei eigene Konten). Stimmt ein Paar nicht, wähle „Keine Umbuchung“: Es zählt dann wieder als Einnahme bzw. Ausgabe und wird nie wieder gepaart.' : 'FinSight paired these itself (same amount, within 3 days, two own accounts). Reject a pair that is wrong: it counts as income/spending again and is never paired again.'}</p>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!!data && !data.pairs.length && !data.rejections.length}>
      {data && <>
        <p><strong>{data.total}</strong> {de ? 'automatisch erkannte Paare' : 'automatically detected pairs'}{data.total > data.limit && <> · {de ? `die neuesten ${data.limit} werden gezeigt` : `showing the newest ${data.limit}`}</>}</p>
        <ul className="review-list">{data.pairs.map(p => <li key={p.key}>
          <span><strong><Money value={p.amount} currency={p.currency} /></strong> · {formatDate(p.outflow.date, language)} → {formatDate(p.inflow.date, language)}<small className="block muted">{p.outflow.account} → {p.inflow.account}{p.outflow.merchant ? ` · ${p.outflow.merchant}` : ''}</small></span>
          <Button variant="outline" disabled={reject.isPending} onClick={() => reject.mutate(p.key)}>{de ? 'Keine Umbuchung' : 'Not a transfer'}</Button></li>)}</ul>
        {!!data.rejections.length && <details><summary>{de ? `Abgelehnte Paare (${data.rejections.length})` : `Rejected pairs (${data.rejections.length})`}</summary><ul className="review-list">{data.rejections.map(r => <li key={r.id}><span><Money value={r.amount} currency={r.currency} /> · {formatDate(r.booking_date, language)}<small className="block muted">{r.label}</small></span><Button variant="ghost" onClick={() => restore.mutate(r.id)}>{de ? 'Wiederherstellen' : 'Restore'}</Button></li>)}</ul></details>}
      </>}
    </QueryState>
    <Feedback error={reject.error || restore.error} />
  </Dialog>
}
