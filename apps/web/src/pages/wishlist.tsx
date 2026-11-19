import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Gift, Plus, Settings2, Trash2, Check } from 'lucide-react'
import { api, send } from '../lib/api'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'
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
  baseline: { currency: string; months_used: number; data_through?: string | null; monthly_income: string; income_sources: Record<string, { monthly_average: string; monthly_lower_quartile: string; months_with_income: number; share: string }>; unassigned_income: { merchant: string; total: string }[]; monthly_consumption: string; monthly_tax: string; expected_surplus: string; conservative_surplus: string; cash_on_hand: string; reserve: string; usable_cash: string; confidence: string; assumptions: string[]; warnings: string[] }
  prefs: { self_names: string[]; reserve_months: number; monthly_tax_reserve: string }
  wishes: WishItem[]; disclaimer: string
}
const DE_MESSAGES: Record<string, string> = {
  'No account is marked as owned; classify accounts before relying on this assessment': 'Kein Konto ist als eigenes Konto markiert; ordne die Konten zu, bevor du dich auf diese Einschätzung verlässt.',
  'Some transfers are uncertain; the consumption figure may be slightly off': 'Einige Umbuchungen sind unsicher; der Konsum kann leicht abweichen.',
  'Transaction data is stale; import a fresh export': 'Die Buchungsdaten sind veraltet; importiere einen aktuellen Export.',
  'Tax accounts exist but no tax outflow was found; set a monthly tax reserve': 'Es gibt Steuerkonten, aber keine Steuerzahlung wurde gefunden; lege eine monatliche Steuerrücklage fest.',
  'No tax cost is modelled; if you owe tax on irregular income, set a monthly tax reserve': 'Steuern sind nicht eingerechnet; falls du auf unregelmäßige Einnahmen Steuern schuldest, lege eine monatliche Steuerrücklage fest.',
  'Some observed balances are stale': 'Einige beobachtete Kontostände sind veraltet.',
  'No observed balances; cash on hand is assumed to be zero': 'Keine beobachteten Kontostände; vorhandenes Geld wird mit null angesetzt.',
  'Running costs of this and earlier wishes would consume the whole expected surplus': 'Die Folgekosten dieses und früherer Wünsche würden den gesamten erwarteten Überschuss aufbrauchen.',
  'Surplus = income - consumption - tax, excluding transfers, savings and your own transfers': 'Überschuss = Einnahmen − Konsum − Steuer, ohne Umbuchungen, Sparen und eigene Überweisungen.',
  'Conservative = lower quartile of monthly surplus; expected = 12-month average': 'Konservativ = unteres Quartil des Monatsüberschusses; erwartet = 12-Monats-Durchschnitt.',
  'Cash on hand uses observed balances, which are not a complete net worth': 'Das vorhandene Geld basiert auf beobachteten Kontoständen und ist kein vollständiges Vermögen.',
}
const DE_PATTERNS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^Only (\d+) complete month\(s\) of data are available$/, m => `Nur ${m[1]} vollständige(r) Monat(e) an Daten verfügbar.`],
  [/^Wish is in (\w+); assessment covers (\w+) only$/, m => `Der Wunsch ist in ${m[1]}; die Einschätzung deckt nur ${m[2]} ab.`],
]
const DE_CONFIDENCE: Record<string, string> = { low: 'niedrig', medium: 'mittel', high: 'hoch' }
function localize(message: string, language: string) {
  if (language !== 'de') return message
  if (DE_MESSAGES[message]) return DE_MESSAGES[message]
  for (const [re, fn] of DE_PATTERNS) { const m = message.match(re); if (m) return fn(m) }
  return message
}
const tone: Record<string, string> = { affordable: 'success', save_up: '', tight: 'warning', not_now: 'danger', unsupported_currency: 'warning' }

export default function WishlistPage() {
  const { t, language } = useLocale()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['wishlist'], queryFn: () => api<Wishlist>('/wishlist') })
  const [create, setCreate] = useState(false)
  const [prefs, setPrefs] = useState(false)
  const [rules, setRules] = useState(false)
  const refresh = () => client.invalidateQueries({ queryKey: ['wishlist'] })
  const update = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => send(`/wishes/${id}`, { status }, 'PATCH'), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: string) => send(`/wishes/${id}`, undefined, 'DELETE'), onSuccess: refresh })
  const data = query.data
  const verdictText = (v: string) => t(`wish_${v}` as never)
  const open = data?.wishes.filter(w => w.status === 'open') ?? []
  const closed = data?.wishes.filter(w => w.status !== 'open') ?? []
  return <>
    <PageHeader title={t('wishlist')} description={t('wishlistIntro')} action={<><Button variant="outline" onClick={() => setRules(true)}>{t('incomeRules')}</Button><Button variant="outline" onClick={() => setPrefs(true)}><Settings2 size={17} />{t('wishPrefs')}</Button><Button onClick={() => setCreate(true)}><Plus size={17} />{t('wishAdd')}</Button></>} />
    <Notice>{data?.disclaimer ?? t('wishDisclaimer')}</Notice>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>
      {data && <>
        <Panel title={t('wishBasis')} description={`${t('wishMonths')}: ${data.baseline.months_used} · ${t('wishConfidence')}: ${language === 'de' ? DE_CONFIDENCE[data.baseline.confidence] ?? data.baseline.confidence : data.baseline.confidence}`}>
          <div className="stat-grid">
            <div className="detail-stat"><span>{t('wishIncome')}</span><Money value={data.baseline.monthly_income} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishConsumption')}</span><Money value={data.baseline.monthly_consumption} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishTax')}</span><Money value={data.baseline.monthly_tax} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishSurplusExpected')}</span><Money value={data.baseline.expected_surplus} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishSurplusConservative')}</span><Money value={data.baseline.conservative_surplus} currency={data.baseline.currency} /></div>
            <div className="detail-stat"><span>{t('wishUsableCash')}</span><Money value={data.baseline.usable_cash} currency={data.baseline.currency} /></div>
          </div>
          {data.baseline.warnings.map((w, i) => <Notice warning key={i}>{localize(w, language)}</Notice>)}
          <details><summary>{t('wishAssumptions')}</summary><ul>{data.baseline.assumptions.map((a, i) => <li key={i}>{localize(a, language)}</li>)}</ul></details>
        </Panel>
        <Panel title={t('incomeSources')}>
          <div className="stat-grid">{(['employment', 'business', 'other'] as const).map(k => { const s = data.baseline.income_sources?.[k]; return s && <div className="detail-stat" key={k}><span>{t(`src_${k}` as never)} · {Math.round(Number(s.share) * 100)} %</span><Money value={s.monthly_average} currency={data.baseline.currency} /><span className="muted">{t('srcWorst')}: <Money value={s.monthly_lower_quartile} currency={data.baseline.currency} /> · {t('srcMonths')}: {s.months_with_income}/{data.baseline.months_used}</span></div> })}</div>
        </Panel>
        {open.some(w => w.assessment && w.assessment.verdict !== 'unsupported_currency') && <PlanChart baseline={data.baseline} wishes={open} />}
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
            {w.assessment.warnings?.map((m, i) => <Notice warning key={i}>{localize(m, language)}</Notice>)}
          </>}
          {w.assessment?.verdict === 'unsupported_currency' && w.assessment.warnings?.map((m, i) => <Notice warning key={i}>{localize(m, language)}</Notice>)}
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
    {rules && data && <IncomeRules unassigned={data.baseline.unassigned_income ?? []} onClose={() => setRules(false)} onDone={refresh} />}
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

type Rule = { id: string; name: string; source: string; pattern: string; match_field: string; account_id: string | null; position: number }

function IncomeRules({ unassigned, onClose, onDone }: { unassigned: { merchant: string; total: string }[]; onClose: () => void; onDone: () => void }) {
  const { t } = useLocale()
  const client = useQueryClient()
  const rulesQuery = useQuery({ queryKey: ['income-rules'], queryFn: () => api<Rule[]>('/income-rules') })
  const accounts = useQuery({ queryKey: ['accounts-light'], queryFn: () => api<{ id: string; name: string }[]>('/accounts') })
  const empty = { name: '', source: 'employment', pattern: '', match_field: 'any', account_id: '' }
  const [form, setForm] = useState(empty)
  const done = () => { client.invalidateQueries({ queryKey: ['income-rules'] }); onDone() }
  const add = useMutation({
    mutationFn: () => send('/income-rules', { name: form.name, source: form.source, pattern: form.pattern, match_field: form.match_field, account_id: form.account_id || null, position: rulesQuery.data?.length ?? 0 }),
    onSuccess: () => { setForm(empty); done() },
  })
  const remove = useMutation({ mutationFn: (id: string) => send(`/income-rules/${id}`, undefined, 'DELETE'), onSuccess: done })
  return <Dialog title={t('incomeRules')} onClose={onClose}>
    <p className="muted">{t('ruleOrderHint')}</p>
    {rulesQuery.data?.length ? <ul>{rulesQuery.data.map(r => <li key={r.id}><Badge>{t(`src_${r.source}` as never)}</Badge> {r.name}{r.pattern && <> · „{r.pattern}“</>} <Button variant="ghost" aria-label={`${t('delete')}: ${r.name}`} onClick={() => remove.mutate(r.id)}><Trash2 size={15} /></Button></li>)}</ul> : <p className="muted">{t('ruleNone')}</p>}
    {unassigned.length > 0 && <details><summary>{t('ruleUnassigned')}</summary><ul>{unassigned.map(u => <li key={u.merchant}>{u.merchant} · <Money value={u.total} currency="EUR" /> <Button variant="ghost" type="button" onClick={() => setForm({ ...form, name: u.merchant, pattern: u.merchant, match_field: 'merchant' })}>{t('ruleUse')}</Button></li>)}</ul></details>}
    <form className="form-stack" onSubmit={e => { e.preventDefault(); add.mutate() }}>
      <Field label={t('ruleName')}><input required maxLength={200} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
      <div className="form-grid">
        <Field label={t('ruleSource')}><select value={form.source} onChange={e => setForm({ ...form, source: e.target.value })}>{['employment', 'business', 'other'].map(k => <option key={k} value={k}>{t(`src_${k}` as never)}</option>)}</select></Field>
        <Field label={t('ruleField')}><select value={form.match_field} onChange={e => setForm({ ...form, match_field: e.target.value })}>{[['any', 'ruleAny'], ['merchant', 'ruleMerchant'], ['description', 'ruleDescription']].map(([v, k]) => <option key={v} value={v}>{t(k as never)}</option>)}</select></Field>
        <Field label={t('rulePattern')} hint={t('rulePatternHint')}><input maxLength={200} value={form.pattern} onChange={e => setForm({ ...form, pattern: e.target.value })} /></Field>
        <Field label={t('ruleAccount')}><select value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })}><option value="">{t('ruleAnyAccount')}</option>{accounts.data?.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
      </div>
      <Feedback error={add.error} />
      <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>{t('cancel')}</Button><Button type="submit" busy={add.isPending}>{t('ruleAdd')}</Button></div>
    </form>
  </Dialog>
}

function PlanChart({ baseline, wishes }: { baseline: Wishlist['baseline']; wishes: WishItem[] }) {
  const { t, language } = useLocale()
  const usable = Number(baseline.usable_cash)
  const expected = Math.max(0, Number(baseline.expected_surplus))
  const conservative = Math.max(0, Number(baseline.conservative_surplus))
  const rows = Array.from({ length: 25 }, (_, m) => ({ month: m, expected: usable + expected * m, conservative: usable + conservative * m }))
  const targets = wishes.filter(w => w.assessment?.cumulative_price).map(w => ({ id: w.id, name: w.name, price: Number(w.assessment!.cumulative_price) }))
  const money = (v: unknown) => formatMoney(String(v), baseline.currency, language)
  const top = Math.max(1, ...targets.map(w => w.price), usable) * 1.3
  return <Panel title={t('planChart')} description={t('planChartText')}>
    <div className="chart-container" role="img" aria-label={t('planChart')}><ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows} margin={{ left: -10, right: 12, top: 16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
        <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} label={{ value: t('planAfter'), position: 'insideBottom', offset: -2, fill: 'var(--muted)', fontSize: 11 }} />
        <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} domain={[0, top]} allowDataOverflow />
        <Tooltip formatter={money} labelFormatter={m => `${t('planAfter')}: ${m}`} contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {targets.map(w => <ReferenceLine key={w.id} y={w.price} stroke="#b5654f" strokeDasharray="4 4" label={{ value: w.name, fill: 'var(--muted)', fontSize: 11, position: 'insideTopLeft', dy: -14 }} />)}
        <Line isAnimationActive={false} type="monotone" name={t('wishExpected')} dataKey="expected" stroke="#287a68" strokeWidth={2.5} dot={false} />
        <Line isAnimationActive={false} type="monotone" name={t('wishConservative')} dataKey="conservative" stroke="#d5aa64" strokeWidth={2.5} dot={false} />
      </LineChart>
    </ResponsiveContainer></div>
  </Panel>
}
