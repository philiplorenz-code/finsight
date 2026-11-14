import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Check, EyeOff, Sparkles } from 'lucide-react'
import { api, items, send } from '../lib/api'
import { periodDates } from '../lib/adapters'
import type { Finding } from '../lib/types'
import type { SettingsData } from './settings'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Feedback, Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Evidence = { query?: { start?: string; end?: string; currency?: string; metric?: string }; as_of?: string; transaction_id?: string; description?: string }
type Answer = { answer: string; evidence?: Evidence[] }
type Usage = { currency: string; runs: { id: string; channel: string; currency?: string | null; state: string; reserved: string; charged: string | null; created_at: string }[] }
export default function InsightsPage() {
  const { t, language } = useLocale(); const client = useQueryClient()
  const defaults = periodDates('month', '', '')
  const [form, setForm] = useState({ topic: 'cashflow', currency: 'EUR', start: defaults.start, end: defaults.end })
  const findings = useQuery({ queryKey: ['findings'], queryFn: () => api<(Finding & { body?: string; evidence?: Evidence[] })[]>('/findings') })
  const usage = useQuery({ queryKey: ['ai-usage'], queryFn: () => api<Usage>('/ai/usage'), retry: false })
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<SettingsData>('/settings') })
  const chat = useMutation({ mutationFn: () => send<Answer>('/ai/chat', form), onSettled: () => { client.invalidateQueries({ queryKey: ['ai-usage'] }); client.invalidateQueries({ queryKey: ['findings'] }) } })
  const state = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => send(`/findings/${encodeURIComponent(id)}`, { status }, 'PATCH'), onSuccess: () => client.invalidateQueries({ queryKey: ['findings'] }) })
  const enabled = !!(settings.data?.ai?.enabled ?? settings.data?.ai_enabled) && !!(settings.data?.ai?.external_consent ?? settings.data?.external_ai_consent) && (!settings.data?.ai || settings.data.ai.budget_currency === 'EUR')
  return <>
    <PageHeader title={t('insights')} description={t('insightsIntro')} /><Notice>{t('aiNote')}</Notice>
    <div className="insights-grid">
      <Panel title={t('assistant')} action={<Sparkles size={20} />}>
        <p className="muted">{language === 'de' ? 'Wähle eine datensparsame Frage. Freie Texteingaben sind in dieser Version bewusst deaktiviert.' : 'Choose a privacy-preserving question. Free-form prompts are intentionally disabled in this release.'}</p>
        <form className="form-stack" onSubmit={e => { e.preventDefault(); chat.mutate() }}>
          <Field label={t('question')}><select value={form.topic} onChange={e => setForm({ ...form, topic: e.target.value })}>
            <option value="cashflow">{language === 'de' ? 'Wie entwickelt sich mein Cashflow?' : 'How is my cash flow changing?'}</option>
            <option value="categories">{language === 'de' ? 'Was zeigen meine Ausgabenkategorien?' : 'What do my spending categories show?'}</option>
            <option value="coverage">{language === 'de' ? 'Wie vollständig sind meine Daten?' : 'How complete is my data?'}</option>
          </select></Field>
          <div className="form-grid">
            <Field label={t('from')}><input required type="date" max={form.end} value={form.start} onChange={e => setForm({ ...form, start: e.target.value })} /></Field>
            <Field label={t('to')}><input required type="date" min={form.start} value={form.end} onChange={e => setForm({ ...form, end: e.target.value })} /></Field>
          </div>
          <Field label={t('currency')}><input required maxLength={3} pattern="[A-Z]{3}" value={form.currency} onChange={e => setForm({ ...form, currency: e.target.value.toUpperCase() })} /></Field>
          <Feedback error={chat.error || settings.error} />
          <Button busy={chat.isPending} disabled={!enabled || form.start > form.end}><Sparkles size={16} />{t('ask')}</Button>
          {!enabled && <Link className="text-link" to="/settings">{t('settings')}<ArrowUpRight size={15} /></Link>}
        </form>
        {chat.data && <div className="ai-answer" aria-live="polite"><Badge>AI · {language === 'de' ? 'Bitte prüfen' : 'Please verify'}</Badge><p>{chat.data.answer}</p><EvidenceLinks evidence={chat.data.evidence} /></div>}
      </Panel>
      <Panel title={t('usage')}>
        <div className="detail-stat"><span>{t('budgetEur')}</span><Money value={settings.data?.ai?.budget_currency === 'EUR' ? settings.data.ai.monthly_limit : undefined} currency="EUR" /></div>
        {settings.data?.ai && settings.data.ai.budget_currency !== 'EUR' && <Notice warning>{language === 'de' ? 'Historische Budgetwährung nicht als EUR bestätigt. Abstimmung erforderlich.' : 'Historical budget currency is not confirmed as EUR. Reconciliation required.'}</Notice>}
        <p className="muted small">{language === 'de' ? 'Reservierung, Modellfreigabe und Kostenlimits werden serverseitig geprüft. Unbestätigte Abrechnung bleibt sichtbar.' : 'Reservations, model approval and spending limits are checked by the server. Unverified billing remains visible.'}</p>
        <QueryState pending={usage.isPending} error={usage.error} retry={usage.refetch} empty={!usage.data?.runs.length}>
          <DataTable headers={[t('date'), t('status'), language === 'de' ? 'Reserviert / Abgerechnet' : 'Reserved / Charged']}>{usage.data?.runs.map(r => <tr key={r.id}>
            <td>{formatDate(r.created_at, language)}</td><td><Badge>{r.state}</Badge></td>
            <td>{r.currency && /^[A-Z]{3}$/.test(r.currency) ? <><Money value={r.reserved} currency={r.currency} /> / <Money value={r.charged} currency={r.currency} /> <Badge tone={r.currency === 'EUR' ? '' : 'warning'}>{r.currency}{r.currency !== 'EUR' ? ' · legacy' : ''}</Badge></> : <span className="muted">{r.reserved} / {r.charged ?? '—'} <Badge tone="warning">{language === 'de' ? 'Währung unbekannt · Abstimmung nötig' : 'Unknown currency · reconciliation needed'}</Badge></span>}</td>
          </tr>)}</DataTable>
        </QueryState>
      </Panel>
    </div>
    <Panel title={t('findings')}>
      <Feedback error={state.error} />
      <QueryState pending={findings.isPending} error={findings.error} retry={findings.refetch} empty={!items(findings.data).length}>
        <div className="findings-list">{items(findings.data).map(f => <article className={`finding ${f.status === 'dismissed' ? 'dismissed' : ''}`} key={f.id}>
          <div className="finding-icon"><Sparkles size={19} /></div>
          <div className="finding-body">
            <div className="finding-heading"><h3>{f.title}</h3><Badge>{f.status || 'open'}</Badge></div><p>{f.body || f.summary}</p>
            <EvidenceLinks evidence={f.evidence} />
            <div className="badge-row"><Button variant="ghost" disabled={state.isPending || f.status === 'acknowledged'} onClick={() => state.mutate({ id: f.id, status: 'acknowledged' })}><Check size={15} />{t('acknowledge')}</Button><Button variant="ghost" disabled={state.isPending || f.status === 'dismissed'} onClick={() => state.mutate({ id: f.id, status: 'dismissed' })}><EyeOff size={15} />{t('dismiss')}</Button></div>
          </div>
        </article>)}</div>
      </QueryState>
    </Panel>
  </>
}
function EvidenceLinks({ evidence }: { evidence?: Evidence[] }) {
  const { t, language } = useLocale()
  if (!evidence?.length) return <small className="muted">{t('evidence')}: {t('noValue')}</small>
  return <details className="evidence-details"><summary>{t('evidence')} ({evidence.length})</summary><ul className="evidence-list">{evidence.map((e, i) => {
    const params = new URLSearchParams()
    if (e.query?.start) params.set('date_from', e.query.start)
    if (e.query?.end) params.set('date_to', e.query.end)
    if (e.query?.currency) params.set('currency', e.query.currency)
    if (e.transaction_id) params.set('detail', e.transaction_id)
    return <li key={i}><Link to={`/transactions?${params}`}>{e.description || e.query?.metric || t('transactions')} →</Link>{e.as_of && <small>{formatDate(e.as_of, language)}</small>}</li>
  })}</ul></details>
}
