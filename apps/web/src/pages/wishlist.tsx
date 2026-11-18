import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Gift, Plus, Settings2, Trash2, Check } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, Dialog, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Assessment = {
  verdict: 'affordable' | 'save_up' | 'tight' | 'not_now' | 'unsupported_currency'
  shortfall?: string; cumulative_price?: string
  months_conservative?: number | null; months_expected?: number | null
  date_conservative?: string | null; date_expected?: string | null
  share_of_annual_surplus?: string | null; surplus_after_follow_up_costs?: string
  required_monthly_for_due_date?: string; on_time_conservative?: boolean; on_time_expected?: boolean
  warnings?: string[]
}
type WishItem = { id: string; name: string; price: string; currency: string; priority: number; due_date?: string | null; follow_up_monthly_cost: string; note: string; status: string; assessment: Assessment | null }
type Wishlist = {
  baseline: { currency: string; months_used: number; data_through?: string | null; monthly_income: string; monthly_consumption: string; monthly_tax: string; expected_surplus: string; conservative_surplus: string; cash_on_hand: string; reserve: string; usable_cash: string; confidence: string; assumptions: string[]; warnings: string[] }
  prefs: { self_names: string[]; reserve_months: number; monthly_tax_reserve: string }
  wishes: WishItem[]; disclaimer: string
}
const tone: Record<string, string> = { affordable: 'success', save_up: '', tight: 'warning', not_now: 'danger', unsupported_currency: 'warning' }

export default function WishlistPage() {
  const { t, language } = useLocale()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['wishlist'], queryFn: () => api<Wishlist>('/wishlist') })
  const [create, setCreate] = useState(false)
  const [prefs, setPrefs] = useState(false)
  const refresh = () => client.invalidateQueries({ queryKey: ['wishlist'] })
  const update = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => send(`/wishes/${id}`, { status }, 'PATCH'), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: string) => send(`/wishes/${id}`, undefined, 'DELETE'), onSuccess: refresh })
  const data = query.data
  const verdictText = (v: string) => t(`wish_${v}` as never)
  const open = data?.wishes.filter(w => w.status === 'open') ?? []
  const closed = data?.wishes.filter(w => w.status !== 'open') ?? []
  return <>
    <PageHeader title={t('wishlist')} description={t('wishlistIntro')} action={<><Button variant="outline" onClick={() => setPrefs(true)}><Settings2 size={17} />{t('wishPrefs')}</Button><Button onClick={() => setCreate(true)}><Plus size={17} />{t('wishAdd')}</Button></>} />
    <Notice>{data?.disclaimer ?? t('wishDisclaimer')}</Notice>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>
      {data && <>
        <Panel title={t('wishBasis')} description={`${t('wishMonths')}: ${data.baseline.months_used} · ${t('wishConfidence')}: ${data.baseline.confidence}`}>
          <div className="stat-grid">
            <div className="detail-stat"><span>{t('wishIncome')}</span><Money value={data.baseline.monthly_income} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishConsumption')}</span><Money value={data.baseline.monthly_consumption} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishTax')}</span><Money value={data.baseline.monthly_tax} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishSurplusExpected')}</span><Money value={data.baseline.expected_surplus} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishSurplusConservative')}</span><Money value={data.baseline.conservative_surplus} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishUsableCash')}</span><Money value={data.baseline.usable_cash} currency={data.baseline.currency} /></div>
          </div>
          {data.baseline.warnings.map((w, i) => <Notice warning key={i}>{w}</Notice>)}
          <details><summary>{t('wishAssumptions')}</summary><ul>{data.baseline.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></details>
        </Panel>
        {!open.length && <Panel><p className="muted"><Gift size={16} /> {t('wishEmpty')}</p></Panel>}
        <div className="buckets-grid">{open.map(w => <Panel key={w.id} className="bucket-card">
          <div className="card-top"><Badge tone={tone[w.assessment?.verdict ?? ''] ?? ''}>{w.assessment ? verdictText(w.assessment.verdict) : '—'}</Badge><Badge>{`P${w.priority}`}</Badge></div>
          <h2>{w.name}</h2>
          <div className="bucket-money"><Money value={w.price} currency={w.currency} /></div>
          {w.assessment && w.assessment.verdict !== 'unsupported_currency' && <>
            {w.assessment.verdict === 'affordable'
              ? <p>{t('wishAffordableText')}</p>
              : <>
                <div className="bucket-meta"><span>{t('wishShortfall')}</span><Money value={w.assessment.shortfall} currency={w.currency} /></div>
                <div className="bucket-meta"><span>{t('wishConservative')}</span><span>{w.assessment.months_conservative != null ? `${w.assessment.months_conservative} ${t('wishMonthsShort')} · ${formatDate(w.assessment.date_conservative ?? undefined, language)}` : t('wishNever')}</span></div>
                <div className="bucket-meta"><span>{t('wishExpected')}</span><span>{w.assessment.months_expected != null ? `${w.assessment.months_expected} ${t('wishMonthsShort')} · ${formatDate(w.assessment.date_expected ?? undefined, language)}` : t('wishNever')}</span></div>
              </>}
            {w.due_date && <div className="bucket-meta muted"><span>{t('due')}</span><span>{formatDate(w.due_date, language)} · {w.assessment.on_time_conservative ? t('wishOnTime') : w.assessment.on_time_expected ? t('wishOnTimeExpected') : t('wishLate')}</span></div>}
            {Number(w.follow_up_monthly_cost) > 0 && <div className="bucket-meta muted"><span>{t('wishFollowUp')}</span><Money value={w.follow_up_monthly_cost} currency={w.currency} /></div>}
            {w.assessment.share_of_annual_surplus != null && <div className="bucket-meta muted"><span>{t('wishShare')}</span><span>{(Number(w.assessment.share_of_annual_surplus) * 100).toFixed(0)} %</span></div>}
            {w.assessment.warnings?.map((m, i) => <Notice warning key={i}>{m}</Notice>)}
          </>}
          {w.assessment?.verdict === 'unsupported_currency' && w.assessment.warnings?.map((m, i) => <Notice warning key={i}>{m}</Notice>)}
          <div className="bucket-actions">
            <Button variant="outline" onClick={() => update.mutate({ id: w.id, status: 'bought' })}><Check size={15} />{t('wishBought')}</Button>
            <Button variant="ghost" aria-label={`${t('delete')}: ${w.name}`} onClick={() => remove.mutate(w.id)}><Trash2 size={17} /></Button>
          </div>
        </Panel>)}</div>
        {!!closed.length && <Panel title={t('wishClosed')}><ul className="obligation-list">{closed.map(w => <li key={w.id}><span>{w.name} · {w.status}</span><Money value={w.price} currency={w.currency} /></li>)}</ul></Panel>}
        <Feedback error={update.error || remove.error} />
      </>}
    </QueryState>
    {create && <WishCreate onClose={() => setCreate(false)} onDone={refresh} />}
    {prefs && data && <Prefs current={data.prefs} onClose={() => setPrefs(false)} onDone={refresh} />}
  </>
}

function WishCreate({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useLocale()
  const [form, setForm] = useState({ name: '', price: '', priority: '3', due_date: '', follow_up_monthly_cost: '', note: '' })
  const mutation = useMutation({
    mutationFn: () => send('/wishes', { name: form.name, price: form.price, priority: Number(form.priority), due_date: form.due_date || null, follow_up_monthly_cost: form.follow_up_monthly_cost || '0', note: form.note }),
    onSuccess: () => { onDone(); onClose() },
  })
  return <Dialog title={t('wishAdd')} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
      <Field label={t('name')}><input required maxLength={300} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
      <div className="form-grid">
        <Field label={t('wishPrice')}><input required type="number" min="0.01" step="0.01" value={form.price} onChange={e => setForm({ ...form, price: e.target.value })} /></Field>
        <Field label={t('wishPriority')} hint={t('wishPriorityHint')}><select value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value })}>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}</select></Field>
        <Field label={t('due')}><input type="date" value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })} /></Field>
        <Field label={t('wishFollowUp')}><input type="number" min="0" step="0.01" value={form.follow_up_monthly_cost} onChange={e => setForm({ ...form, follow_up_monthly_cost: e.target.value })} /></Field>
      </div>
      <Field label={t('wishNote')}><input maxLength={2000} value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} /></Field>
      <Feedback error={mutation.error} />
      <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>{t('cancel')}</Button><Button type="submit" busy={mutation.isPending}>{t('save')}</Button></div>
    </form>
  </Dialog>
}

function Prefs({ current, onClose, onDone }: { current: Wishlist['prefs']; onClose: () => void; onDone: () => void }) {
  const { t } = useLocale()
  const [form, setForm] = useState({ names: current.self_names.join(', '), reserve: String(current.reserve_months), tax: current.monthly_tax_reserve })
  const mutation = useMutation({
    mutationFn: () => send('/wishlist/prefs', { self_names: form.names.split(',').map(n => n.trim()).filter(Boolean), reserve_months: Number(form.reserve), monthly_tax_reserve: form.tax || '0' }, 'PUT'),
    onSuccess: () => { onDone(); onClose() },
  })
  return <Dialog title={t('wishPrefs')} onClose={onClose}>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
      <Field label={t('wishSelfNames')} hint={t('wishSelfNamesHint')}><input maxLength={600} value={form.names} onChange={e => setForm({ ...form, names: e.target.value })} /></Field>
      <div className="form-grid">
        <Field label={t('wishReserveMonths')} hint={t('wishReserveHint')}><input type="number" min="0" max="24" value={form.reserve} onChange={e => setForm({ ...form, reserve: e.target.value })} /></Field>
        <Field label={t('wishTaxReserve')} hint={t('wishTaxHint')}><input type="number" min="0" step="0.01" value={form.tax} onChange={e => setForm({ ...form, tax: e.target.value })} /></Field>
      </div>
      <Feedback error={mutation.error} />
      <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>{t('cancel')}</Button><Button type="submit" busy={mutation.isPending}>{t('save')}</Button></div>
    </form>
  </Dialog>
}
