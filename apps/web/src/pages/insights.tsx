import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Check, EyeOff, MessageCircleQuestion, Sparkles } from 'lucide-react'
import { api, items, send } from '../lib/api'
import { periodDates } from '../lib/adapters'
import type { Finding } from '../lib/types'
import type { SettingsData } from './settings'
import { formatDate, useLocale } from '../lib/i18n'
import { AnomalyPanel } from '../components/anomalies'
import { label } from '../lib/labels'
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
    <PageHeader title={t('insights')} description={t('insightsIntro')} /><Notice>{t('aiNote')}</Notice><AnomalyPanel days={90} limit={20} />
    <Analyst enabled={enabled} />
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
            <td>{formatDate(r.created_at, language)}</td><td><Badge>{label('runState', r.state, language)}</Badge></td>
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
            <div className="finding-heading"><h3>{f.title}</h3><Badge>{label('findingStatus', f.status || 'open', language)}</Badge></div><p>{f.body || f.summary}</p>
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


type AskResult = { run_id: string; answer: string; sent: Record<string, unknown>; steps?: { tool: string; used: boolean }[]; input_tokens?: number | null; output_tokens?: number | null }
type Preview = { context: Record<string, unknown>; system_prompt: string }
const QUESTIONS_DE = ['Wo kann ich am meisten sparen?', 'Wie belastbar ist mein Überschuss, besonders mit dem Gewerbe?', 'Welche Versicherungen und Verträge sollte ich prüfen?', 'Kann ich mir meine Wünsche leisten, und in welcher Reihenfolge?', 'Was fällt dir an meinen Einnahmen und Ausgaben der letzten Monate auf?']
const QUESTIONS_EN = ['Where can I save the most?', 'How reliable is my surplus, especially with the business?', 'Which insurances and contracts should I review?', 'Can I afford my wishes, and in which order?', 'What stands out in my income and spending lately?']

function Analyst({ enabled }: { enabled: boolean }) {
  const { language } = useLocale()
  const de = language === 'de'
  const client = useQueryClient()
  const [question, setQuestion] = useState('')
  const [names, setNames] = useState(false)
  const preview = useMutation({ mutationFn: () => api<Preview>(`/ai/context?include_names=${names}&question=${encodeURIComponent(question)}`) })
  const ask = useMutation({
    mutationFn: () => send<AskResult>('/ai/ask', { question, include_names: names }),
    onSettled: () => { client.invalidateQueries({ queryKey: ['ai-usage'] }); client.invalidateQueries({ queryKey: ['findings'] }) },
  })
  return <Panel title={de ? 'KI-Analyst' : 'AI analyst'} action={<MessageCircleQuestion size={20} />} description={de
    ? 'Stell eine beliebige Frage zu deinen Finanzen. Die KI sieht nie einzelne Buchungen, nur gerundete Kennzahlen aus deinen Auswertungen (Durchschnitte, Kategorien, Vertragsklassen, Vermögen, Wunsch-Bewertung).'
    : 'Ask anything about your finances. The AI never sees single bookings, only rounded figures from your analysis.'}>
    <AutoFindings de={de} />
    <div className="chip-row">{(de ? QUESTIONS_DE : QUESTIONS_EN).map(q => <Button key={q} variant="outline" type="button" onClick={() => setQuestion(q)}>{q}</Button>)}</div>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); ask.mutate() }}>
      <Field label={de ? 'Deine Frage' : 'Your question'} hint={de ? 'Bitte keine Namen, Kontonummern oder Adressen eintippen: Der Text geht an den KI-Anbieter.' : 'Please do not type names, account numbers or addresses: the text goes to the AI provider.'}>
        <textarea rows={3} required minLength={3} maxLength={500} value={question} onChange={e => setQuestion(e.target.value)} />
      </Field>
      <label className="check-row"><input type="checkbox" checked={names} onChange={e => setNames(e.target.checked)} /> <span>{de ? 'Anbieter- und Wunschnamen mitsenden (aus, wenn du es nicht brauchst)' : 'Include payee and wish names (off unless needed)'}</span></label>
      <div className="form-actions">
        <Button variant="outline" type="button" busy={preview.isPending} onClick={() => preview.mutate()}>{de ? 'Was wird gesendet?' : 'What is sent?'}</Button>
        <Button busy={ask.isPending} disabled={!enabled || question.trim().length < 3}><Sparkles size={16} />{de ? 'Analyst fragen' : 'Ask analyst'}</Button>
      </div>
      {!enabled && <Notice warning>{de ? 'KI ist noch nicht freigegeben. ' : 'AI is not enabled yet. '}<Link className="text-link" to="/settings">{de ? 'Einstellungen' : 'Settings'}<ArrowUpRight size={15} /></Link></Notice>}
      <Feedback error={ask.error || preview.error} />
    </form>
    {preview.data && <details open><summary>{de ? 'Genau diese Daten gehen an die KI (ohne deine Frage)' : 'Exactly this data goes to the AI (without your question)'}</summary><pre className="json-preview">{JSON.stringify(preview.data.context, null, 1)}</pre></details>}
    {ask.data && <div className="ai-answer" role="status"><h3>{de ? 'Antwort' : 'Answer'}</h3><p style={{ whiteSpace: 'pre-wrap' }}>{ask.data.answer}</p>
      <p className="muted small">{ask.data.input_tokens ?? '—'} / {ask.data.output_tokens ?? '—'} tokens · {de ? 'Planungshilfe, keine Anlage-, Steuer- oder Rechtsberatung.' : 'Planning aid, not investment, tax or legal advice.'}</p>
      {!!ask.data.steps?.length && <p className="muted">{de ? 'Analyseschritte' : 'Analysis steps'}: {ask.data.steps.map((x) => `${x.tool}${x.used ? '' : ' (leer)'}`).join(' → ')}</p>}<details><summary>{de ? 'Gesendete Daten dieser Antwort' : 'Data sent for this answer'}</summary><pre className="json-preview">{JSON.stringify(ask.data.sent, null, 1)}</pre></details></div>}
  </Panel>
}

type AutoFinding = { code: string; title: string; severity: string; confidence: string; impact_monthly: number | null }
function AutoFindings({ de }: { de: boolean }) {
  const query = useQuery({ queryKey: ['ai-findings'], queryFn: () => api<AutoFinding[]>('/ai/findings') })
  if (!Array.isArray(query.data) || !query.data.length) return null
  return <details open><summary>{de ? `Automatische Auffälligkeiten (${query.data.length}, ohne KI berechnet)` : `Automatic findings (${query.data.length}, computed without AI)`}</summary>
    <ul>{query.data.map((f, i) => <li key={`${f.code}-${i}`}><Badge tone={f.severity === 'high' ? 'warning' : ''}>{f.severity}</Badge> {f.title}{f.impact_monthly != null && <span className="muted"> · {de ? 'Wirkung' : 'impact'} ≈ {f.impact_monthly} €/{de ? 'Mon.' : 'mo.'}</span>} <span className="muted small">({de ? 'Konfidenz' : 'confidence'}: {f.confidence})</span></li>)}</ul>
  </details>
}
