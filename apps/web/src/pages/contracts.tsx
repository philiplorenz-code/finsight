import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { api, items } from '../lib/api'
import type { Contract } from '../lib/types'
import { normalizeContract, type RawContract } from '../lib/adapters'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Dialog, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'
export default function ContractsPage() {
  const { t, language } = useLocale()
  const query = useQuery({ queryKey: ['contracts'], queryFn: async () => { const data = await api<{ items: RawContract[]; warnings?: string[] }>('/contracts'); return { items: items(data).map(normalizeContract), warnings: data.warnings } } })
  const [detail, setDetail] = useState<Contract | null>(null)
  return <><PageHeader title={t('contracts')} description={t('contractsIntro')} /><Notice>{t('contractNote')}</Notice>{query.data?.warnings?.map((w, i) => <Notice key={i} warning>{w}</Notice>)}<Panel><QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!query.data?.items.length}><DataTable headers={[t('name'), t('frequency'), t('annual'), t('nextCharge'), t('confidence'), '']}>{query.data?.items.map(c => <tr key={c.id}><td><strong>{c.name}</strong><small className="block muted">{c.source || t('inferred')}</small></td><td>{c.frequency || '—'}</td><td><Money value={c.annualized_cost} currency={c.currency} /></td><td>{formatDate(c.next_charge, language)}</td><td><Badge>{c.confidence ?? '—'}</Badge></td><td><Button variant="ghost" onClick={() => setDetail(c)} aria-label={`${t('details')}: ${c.name}`}><ChevronRight size={18} /></Button></td></tr>)}</DataTable></QueryState></Panel>{detail && <Dialog title={detail.name} onClose={() => setDetail(null)}><div className="detail-stat"><span>{t('annual')}</span><Money value={detail.annualized_cost} currency={detail.currency} /></div>{detail.price_change != null && <div className="detail-stat"><span>{language === 'de' ? 'Preisänderung' : 'Price change'}</span><Money value={detail.price_change} currency={detail.currency} /></div>}<h3>{t('evidence')}</h3><ul className="evidence-list">{detail.evidence?.map((e, i) => <li key={i}>{e.description}{e.transaction_id && <Link to={`/transactions?detail=${encodeURIComponent(e.transaction_id)}`}>{t('transactions')} →</Link>}</li>)}</ul>{!detail.evidence?.length && <p className="muted">{t('noValue')}</p>}</Dialog>}</>
}
