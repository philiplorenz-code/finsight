import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, ChevronLeft, ChevronRight, Search, SlidersHorizontal } from 'lucide-react'
import { api, items, queryString, send } from '../lib/api'
import type { Account, Transaction } from '../lib/types'
import { formatDate, useLocale } from '../lib/i18n'
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
  return <><PageHeader title={t('transactions')} description={t('transactionsIntro')} /><div className="panel transaction-panel">
    <div className="transaction-toolbar"><form className="search-field" onSubmit={e => { e.preventDefault(); update('search', search) }}><Search size={17} /><input aria-label={t('search')} placeholder={language === 'de' ? 'Buchungen durchsuchen …' : 'Search transactions…'} value={search} onChange={e => setSearch(e.target.value)} /><Button variant="ghost" type="submit">{t('search')}</Button></form><select aria-label={t('account')} value={params.get('account_id') || ''} onChange={e => update('account_id', e.target.value)}><option value="">{t('all')} · {t('accounts')}</option>{items(accounts.data).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select><Button variant="outline" onClick={() => setExpanded(e => !e)} aria-expanded={expanded}><SlidersHorizontal size={16} />Filter</Button></div>
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
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!rows.length}><DataTable headers={[t('merchant'), t('date'), t('category'), t('account'), t('amount'), '']}>{rows.map(row => <tr key={row.id}><td><div className="transaction-name"><span className={`transaction-icon ${row.is_transfer ? 'transfer' : Number(row.amount) >= 0 ? 'positive' : ''}`}>{row.is_transfer ? <ArrowLeftRight size={17} /> : (row.merchant || row.counterparty || '?').slice(0, 1).toUpperCase()}</span><div><strong>{row.merchant || row.counterparty || row.description || '—'}</strong><small>{row.description}</small>{row.pending && <Badge tone="warning">{t('pending')}</Badge>}</div></div></td><td className="nowrap muted">{formatDate(row.booking_date || row.date, language)}</td><td><Badge>{row.is_transfer ? t('transfer') : row.category || '—'}</Badge></td><td className="muted">{row.account_name || row.account_id || '—'}</td><td className="text-right"><Money value={row.amount} currency={row.currency} className={Number(row.amount) >= 0 ? 'positive-text' : ''} /></td><td><Button variant="ghost" aria-label={`${t('details')}: ${row.merchant || row.id}`} onClick={() => update('detail', row.id)}><ChevronRight size={18} /></Button></td></tr>)}</DataTable></QueryState><div className="pagination"><span>{t('page')} {page}{total !== undefined && <> · {total} {t('transactions')}</>}</span><div><Button variant="outline" disabled={page === 1 || query.isFetching} onClick={() => update('page', String(page - 1))}><ChevronLeft size={16} />{t('previous')}</Button><Button variant="outline" disabled={!hasMore || query.isFetching} onClick={() => update('page', String(page + 1))}>{t('next')}<ChevronRight size={16} /></Button></div></div></div>{selected && <TransactionDetail id={selected} onClose={() => update('detail', '')} />}</>
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
      {query.data.warnings?.map((w, i) => <Notice key={i} warning>{w}</Notice>)}
      <h3>{t('correction')}</h3><p className="muted small">{t('correctionText')}</p>
      <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate(false) }}>
        <Field label={t('category')}><input value={category ?? query.data.effective_category ?? query.data.category ?? ''} onChange={e => setCategory(e.target.value)} maxLength={120} /></Field>
        <Field label={t('tags')} hint={language === 'de' ? 'Mit Komma trennen.' : 'Separate with commas.'}><input value={tags ?? query.data.tags?.join(', ') ?? ''} onChange={e => setTags(e.target.value)} maxLength={1000} /></Field>
        <Feedback error={mutation.error} success={mutation.isSuccess} /><div className="form-actions"><Button variant="outline" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate(true)}>{t('reset')}</Button><Button busy={mutation.isPending}>{t('save')}</Button></div>
      </form><details className="source-details"><summary>{t('source')}</summary><pre>{JSON.stringify(query.data.source || {}, null, 2)}</pre></details>
    </>}</QueryState>
  </Dialog>
}
