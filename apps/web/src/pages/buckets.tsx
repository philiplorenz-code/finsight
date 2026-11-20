import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Plus, PiggyBank, ArrowUpRight, Settings2 } from 'lucide-react'
import { api, items, send } from '../lib/api'
import type { Account } from '../lib/types'
import { BucketManage } from '../components/bucket-manage'
import { AccountSelect } from '../components/account-select'
import { normalizeBucket, type RawBucket } from '../lib/adapters'
import { formatDate, useLocale } from '../lib/i18n'
import { localizeWarning } from '../lib/warnings'
import { Badge, Button, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

export default function BucketsPage() {
  const { t, language } = useLocale()
  const query = useQuery({ queryKey: ['buckets'], queryFn: async () => items(await api<RawBucket[]>('/buckets')).map(normalizeBucket) })
  const [create, setCreate] = useState(false)
  const [selected, setSelected] = useState<{ bucket: RawBucket; mode: 'fund' | 'obligation' } | null>(null)
  const [managing, setManaging] = useState<RawBucket | null>(null)
  return <>
    <PageHeader title={t('buckets')} description={t('bucketsIntro')} action={<Button onClick={() => setCreate(true)}><Plus size={17} />{t('createBucket')}</Button>} />
    <Notice>{t('allocationNote')}</Notice>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!query.data?.length}>
      <div className="buckets-grid">{query.data?.map(b => {
        const funded = b.funded_amount ?? b.allocated_amount
        const percent = b.target_amount && Number(b.target_amount) > 0 && funded !== undefined ? Math.min(100, Math.max(0, Number(funded) / Number(b.target_amount) * 100)) : undefined
        return <Panel key={b.id} className="bucket-card">
          <div className="card-top"><span className="bucket-icon"><PiggyBank size={23} /></span><Badge>{t(b.kind === 'real' ? 'real' : 'virtual')}</Badge></div>
          <h2>{b.name}</h2>
          <div className="bucket-money"><Money value={funded} currency={b.currency} /><span>/ <Money value={b.target_amount} currency={b.currency} /></span></div>
          <div className="progress-track" role="progressbar" aria-label={b.name} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent || 0}%` }} /></div>
          {b.warnings?.map((w, i) => <Notice warning key={i}>{localizeWarning(w, language)}</Notice>)}
          <div className="bucket-meta"><span>{t('required')}</span><Money value={b.required_monthly} currency={b.currency} /></div>{b.goal && <GoalLine goal={b.goal} currency={b.currency} de={language === 'de'} />}
          <div className="bucket-meta muted"><span><CalendarDays size={14} />{t('due')}</span><span>{formatDate(b.due_date, language)}</span></div>
          {!!b.obligations?.length && <ul className="obligation-list">{b.obligations.map(o => <li key={o.id}><span>{o.name}</span><Money value={o.amount} currency={b.currency} /></li>)}</ul>}
          <div className="bucket-actions"><Button variant="outline" onClick={() => setSelected({ bucket: b, mode: 'fund' })}>{t('fund')}<ArrowUpRight size={15} /></Button><Button variant="ghost" onClick={() => setSelected({ bucket: b, mode: 'obligation' })} aria-label={`${t('addObligation')}: ${b.name}`}><Plus size={17} /></Button><Button variant="ghost" onClick={() => setManaging(b)} aria-label={`${language === 'de' ? 'Verwalten' : 'Manage'}: ${b.name}`}><Settings2 size={17} /></Button></div>
        </Panel>
      })}</div>
    </QueryState>
    {create && <BucketCreate onClose={() => setCreate(false)} />}
    {managing && <BucketManage bucket={managing} onClose={() => setManaging(null)} />}
    {selected && <BucketAction bucket={selected.bucket} mode={selected.mode} onClose={() => setSelected(null)} />}
  </>
}
function BucketCreate({ onClose }: { onClose: () => void }) {
  const { t } = useLocale(); const client = useQueryClient()
  const { language } = useLocale(); const de = language === 'de'
  const [form, setForm] = useState({ name: '', kind: 'virtual', currency: 'EUR', target: '', due_date: '' })
  const [accountId, setAccountId] = useState('')
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts'), enabled: form.kind === 'real' })
  const eligible = (accounts.data ?? []).filter(a => a.currency === form.currency && a.included !== false && a.ownership === 'owned' && a.purpose !== 'investment')
  const chosen = eligible.find(a => a.id === accountId)
  const mutation = useMutation({
    mutationFn: async () => {
      const bucket = await send<{ id: string }>('/buckets', { ...form, target: form.target || null, due_date: form.due_date || null })
      // An account-backed pot earmarks the chosen account: the target, or else its current balance.
      const amount = form.target || (chosen?.balance && Number(chosen.balance) > 0 ? String(chosen.balance) : '')
      if (form.kind === 'real' && accountId && amount) await send(`/buckets/${encodeURIComponent(bucket.id)}/allocations`, { allocations: [{ account_id: accountId, amount }] }, 'PUT')
      return bucket
    },
    onSuccess: () => { client.invalidateQueries({ queryKey: ['buckets'] }); onClose() },
  })
  return <Dialog title={t('createBucket')} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
      <Field label={t('name')}><input required maxLength={120} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
      <div className="form-grid">
        <Field label={t('kind')}><select value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}><option value="virtual">{t('virtual')}</option><option value="real">{t('real')}</option></select></Field>
        <Field label={t('currency')}><input value={form.currency} pattern="[A-Z]{3}" maxLength={3} required onChange={e => setForm({ ...form, currency: e.target.value.toUpperCase() })} /></Field>
        <Field label={t('target')}><input type="number" min="0.01" step="0.01" value={form.target} onChange={e => setForm({ ...form, target: e.target.value })} /></Field>
        <Field label={t('due')}><input type="date" lang={de ? 'de-DE' : 'en-GB'} value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })} /></Field>
      </div>
      {form.kind === 'real' && <>
        <AccountSelect accounts={eligible} value={accountId} onChange={setAccountId} anyLabel={de ? 'Konto wählen …' : 'Choose account…'} label={de ? 'Gebunden an Konto' : 'Backed by account'} />
        {chosen && <p className="muted small">{de ? 'Aktueller Stand' : 'Current balance'}: <Money value={chosen.balance ?? null} currency={chosen.currency} /> · {form.target ? (de ? 'Der Zielbetrag wird auf diesem Konto reserviert.' : 'The target is earmarked on this account.') : (de ? 'Ohne Ziel wird der aktuelle Stand reserviert.' : 'Without a target the current balance is earmarked.')}</p>}
      </>}
      <Feedback error={mutation.error} /><Button busy={mutation.isPending} disabled={form.kind === 'real' && !accountId}>{t('createBucket')}</Button>
    </form>
  </Dialog>
}
function BucketAction({ bucket, mode, onClose }: { bucket: RawBucket; mode: 'fund' | 'obligation'; onClose: () => void }) {
  const { t, language } = useLocale(); const client = useQueryClient()
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts'), enabled: mode === 'fund' })
  const eligible = accounts.data?.filter(a => a.currency === bucket.currency && a.included !== false && a.ownership === 'owned' && a.purpose !== 'investment')
  const [allocations, setAllocations] = useState<Record<string, string>>(() => Object.fromEntries((bucket.allocations || []).map(a => [a.account_id, a.amount])))
  const [form, setForm] = useState({ name: '', amount: '', period: 'yearly', due_date: '', scheduled_contributions: '' })
  const mutation = useMutation({
    mutationFn: () => mode === 'fund'
      ? send(`/buckets/${encodeURIComponent(bucket.id)}/allocations`, { allocations: Object.entries(allocations).filter(([, amount]) => amount !== '' && Number(amount) > 0).map(([account_id, amount]) => ({ account_id, amount })) }, 'PUT')
      : send(`/buckets/${encodeURIComponent(bucket.id)}/obligations`, { ...form, due_date: form.due_date || null, scheduled_contributions: form.scheduled_contributions || '0' }),
    onSuccess: () => { client.invalidateQueries({ queryKey: ['buckets'] }); client.invalidateQueries({ queryKey: ['overview'] }); onClose() },
  })
  return <Dialog title={`${t(mode === 'fund' ? 'fund' : 'addObligation')}: ${bucket.name}`} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
      {mode === 'fund' ? <>
        <Notice>{t('allocationNote')}</Notice>
        <QueryState pending={accounts.isPending} error={accounts.error} retry={accounts.refetch} empty={!eligible?.length}>
          {eligible?.map(a => <Field key={a.id} label={`${a.name} · ${a.currency}`}><input type="number" min="0" step="0.01" value={allocations[a.id] || ''} onChange={e => setAllocations({ ...allocations, [a.id]: e.target.value })} /></Field>)}
        </QueryState>
        {accounts.data?.filter(a => allocations[a.id] && !eligible?.some(e => e.id === a.id)).map(a => <Field key={a.id} label={`${a.name} · ${language === 'de' ? 'Nicht mehr geeignet: nur entfernen' : 'No longer eligible: remove only'}`}><Button type="button" variant="outline" onClick={() => setAllocations({ ...allocations, [a.id]: '' })}>{t('reset')} · <Money value={allocations[a.id]} currency={a.currency} /></Button></Field>)}
      </> : <>
        <Field label={t('name')}><input required maxLength={120} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label={`${t('amount')} (${bucket.currency})`}><input required type="number" min="0.01" step="0.01" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></Field>
        <Field label={t('frequency')}><select value={form.period} onChange={e => setForm({ ...form, period: e.target.value })}>{(['monthly', 'quarterly', 'yearly'] as const).map(p => <option key={p} value={p}>{t(p)}</option>)}<option value="once">{language === 'de' ? 'Einmalig' : 'Once'}</option></select></Field>
        <Field label={t('due')}><input type="date" value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })} /></Field>
        <Field label={language === 'de' ? 'Fest geplante Beiträge bis zur Fälligkeit' : 'Explicitly scheduled contributions before due date'} hint={language === 'de' ? 'Nicht erneut als Ausgaben zählen.' : 'Not counted again as expenses.'}><input type="number" min="0" step="0.01" value={form.scheduled_contributions} onChange={e => setForm({ ...form, scheduled_contributions: e.target.value })} /></Field>
      </>}
      <Feedback error={mutation.error} /><Button busy={mutation.isPending} disabled={mode === 'fund' && (accounts.isPending || !!accounts.error)}>{t('save')}</Button>
    </form>
  </Dialog>
}

type Goal = { status: string; required_monthly: string; planned_monthly: string; months_left?: number | null; projected_at_due?: string | null; target: string }
const GOAL_TEXT: Record<string, [string, string, string]> = {
  done: ['Ziel erreicht', 'Goal reached', 'ok'], on_track: ['Im Plan', 'On track', 'ok'], tight: ['Knapp', 'Tight', 'warning'],
  behind: ['Hinkt hinterher', 'Behind', 'over'], overdue: ['Fälligkeit verpasst', 'Past due', 'over'], no_deadline: ['Ohne Datum', 'No deadline', 'none'],
}
function GoalLine({ goal, currency, de }: { goal: Goal; currency: string; de: boolean }) {
  const [deText, enText, tone] = GOAL_TEXT[goal.status] ?? [goal.status, goal.status, 'none']
  return <div className="goal-line">
    <span className={`plan-dot ${tone}`} aria-hidden="true" /><strong>{de ? deText : enText}</strong>
    {goal.months_left != null && goal.status !== 'done' && <span className="muted small">{de ? 'Dauerauftrag' : 'Standing order'} <Money value={goal.planned_monthly} currency={currency} /> {de ? 'von nötigen' : 'of needed'} <Money value={goal.required_monthly} currency={currency} />/{de ? 'Monat' : 'month'} · {de ? 'bis Fälligkeit' : 'by due date'} <Money value={goal.projected_at_due} currency={currency} /></span>}
  </div>
}
