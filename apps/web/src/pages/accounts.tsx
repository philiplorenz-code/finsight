import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Wallet, Pencil, Landmark } from 'lucide-react'
import { api, items, send } from '../lib/api'
import type { Account } from '../lib/types'
import { formatDate, useLocale } from '../lib/i18n'
import { ProviderFilter } from './transactions'
import { PURPOSE_DE, PURPOSE_EN } from '../components/new-accounts'
import { Badge, Button, DataTable, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'
import { NewAccountsPrompt } from '../components/new-accounts'

export default function AccountsPage() {
  const { t, language } = useLocale()
  const query = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[] | { items: Account[] }>('/accounts') })
  const [editing, setEditing] = useState<Account | null>(null)
  const [detail, setDetail] = useState<Account | null>(null)
  const [provider, setProvider] = useState('')
  const shown = items(query.data).filter(a => !provider || (provider === '__none' ? !a.provider : a.provider === provider))
  return <><PageHeader title={t('accounts')} description={t('accountsIntro')} /><NewAccountsPrompt /><Notice>{t('balanceWarning')}</Notice><div className="filter-grid account-filter"><ProviderFilter value={provider === '__none' ? '' : provider} onChange={setProvider} /><label className="checkbox"><input type="checkbox" checked={provider === '__none'} onChange={e => setProvider(e.target.checked ? '__none' : '')} />{language === 'de' ? 'Nur Konten ohne Bank' : 'Only accounts without bank'}</label></div><QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!items(query.data).length} importLink><div className="accounts-grid">{shown.map(account => <Panel key={account.id} className="account-card"><div className="card-top"><span className="account-icon"><Wallet size={23} /></span><Button variant="ghost" aria-label={`${t('edit')}: ${account.name}`} onClick={() => setEditing(account)}><Pencil size={16} /></Button></div><div className="account-heading"><h2>{account.name}</h2><Badge>{account.currency}</Badge></div>{account.provider ? <p className="provider-line"><Landmark size={13} /> {account.provider}{account.provider_source === 'manual' ? '' : (language === 'de' ? ' · erkannt' : ' · detected')}</p> : <p className="provider-line muted">{language === 'de' ? 'Bank unbekannt – über ✎ festlegen' : 'Bank unknown – set via ✎'}</p>}<p className="muted small">{account.purpose || account.ownership || '—'}</p><Money value={account.balance} currency={account.currency} /><div className="account-bottom"><span className="muted small">{formatDate(account.balance_date, language)}</span><Button variant="ghost" onClick={() => setDetail(account)}>{t('balanceHistory')}</Button></div><div className="badge-row">{account.included === false && <Badge tone="warning">{language === 'de' ? 'Ausgeschlossen' : 'Excluded'}</Badge>}{account.inactive && <Badge>{t('inactive')}</Badge>}</div></Panel>)}</div></QueryState>{editing && <AccountEditor account={editing} onClose={() => setEditing(null)} />}{detail && <AccountHistory account={detail} onClose={() => setDetail(null)} />}</>
}
function AccountEditor({ account, onClose }: { account: Account; onClose: () => void }) {
  const { t, language } = useLocale(); const client = useQueryClient()
  const [form, setForm] = useState({ name: account.name, purpose: account.purpose || '', included: account.included !== false, ownership: account.ownership || 'unknown', inactive: !!account.inactive, provider: account.provider || '' })
  const providers = useQuery({ queryKey: ['account-providers'], queryFn: () => api<{ known: string[]; used: string[] }>('/account-providers') })
  const mutation = useMutation({ mutationFn: () => send(`/accounts/${encodeURIComponent(account.id)}`, { ...form, purpose: form.purpose || null }, 'PATCH'), onSuccess: () => { client.invalidateQueries({ queryKey: ['accounts'] }); client.invalidateQueries({ queryKey: ['overview'] }); onClose() } })
  return <Dialog title={`${t('edit')}: ${account.name}`} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
      <Field label={t('name')}><input required maxLength={120} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label={t('purpose')}><select value={form.purpose} onChange={e => setForm({ ...form, purpose: e.target.value })}><option value="">—</option>{['checking', 'savings', 'investment', 'credit', 'cash', 'other', 'mirror'].map(p => <option key={p} value={p}>{(language === 'de' ? PURPOSE_DE : PURPOSE_EN)[p] ?? p}</option>)}</select></Field>
      <Field label={t('ownership')}><select value={form.ownership} onChange={e => setForm({ ...form, ownership: e.target.value })}><option value="unknown">Unknown / Unbekannt</option><option value="owned">Owned / Eigen</option><option value="external">External / Extern</option></select></Field>
      <Field label={language === 'de' ? 'Bank / Anbieter' : 'Bank / provider'} hint={language === 'de' ? 'Leer lassen, um die automatische Erkennung zu nutzen.' : 'Leave empty to use automatic detection.'}><input list="provider-options" maxLength={80} value={form.provider} onChange={e => setForm({ ...form, provider: e.target.value })} /><datalist id="provider-options">{[...new Set([...(providers.data?.used ?? []), ...(providers.data?.known ?? [])])].map(p => <option key={p} value={p} />)}</datalist></Field>
      <label className="checkbox"><input type="checkbox" checked={form.included} onChange={e => setForm({ ...form, included: e.target.checked })} />{t('included')}</label>
      <label className="checkbox"><input type="checkbox" checked={form.inactive} onChange={e => setForm({ ...form, inactive: e.target.checked })} />{t('inactive')}</label>
      <Feedback error={mutation.error} />
      <div className="form-actions"><Button variant="outline" type="button" onClick={onClose}>{t('cancel')}</Button><Button busy={mutation.isPending}>{t('save')}</Button></div>
    </form>
  </Dialog>
}
function AccountHistory({ account, onClose }: { account: Account; onClose: () => void }) {
  const { t, language } = useLocale()
  const query = useQuery({ queryKey: ['account', account.id], queryFn: async () => ({ balance_history: (await api<{ observed_date: string; amount: string }[]>(`/accounts/${encodeURIComponent(account.id)}/balances`)).map(b => ({ date: b.observed_date, balance: b.amount })) }) })
  return <Dialog title={`${account.name} · ${t('balanceHistory')}`} onClose={onClose}><Notice>{t('balanceWarning')}</Notice><QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!query.data?.balance_history?.length}><DataTable headers={[t('date'), t('amount')]}>{query.data?.balance_history?.map((p, i) => <tr key={i}><td>{formatDate(p.date, language)}</td><td><Money value={p.balance} currency={account.currency} /></td></tr>)}</DataTable></QueryState></Dialog>
}
