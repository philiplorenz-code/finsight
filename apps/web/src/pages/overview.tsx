import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowUpRight, ArrowRight, CalendarDays, PiggyBank, Wallet, Sparkles, ShieldCheck } from 'lucide-react'
import { api, queryString } from '../lib/api'
import { overviewForCurrency, periodDates, type RawOverview } from '../lib/adapters'
import { formatDate, useLocale } from '../lib/i18n'
import { localizeWarning } from '../lib/warnings'
import { Field, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'
import { CashflowChart, SpendingChart } from '../components/charts'
import { NewAccountsPrompt } from '../components/new-accounts'
import { HealthPanel } from '../components/health-panel'

export default function OverviewPage() {
  const { t, language } = useLocale()
  const [period, setPeriod] = useState('month')
  const [currency, setCurrency] = useState('EUR')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const today = periodDates('month', '', '').end
  const validPeriod = period === 'asof' ? !!to && to <= today : period !== 'custom' || (!!from && !!to && from <= to)
  const range = validPeriod ? periodDates(period, from, to) : undefined
  const rangeLabel = range ? `${formatDate(range.start, language)} – ${formatDate(range.end, language)}` : t(period === 'asof' ? 'asofDate' : 'custom')
  const query = useQuery({
    queryKey: ['overview', period, currency, from, to],
    queryFn: async () => overviewForCurrency(await api<RawOverview>(`/overview${queryString(periodDates(period, from, to))}`), currency),
    enabled: validPeriod,
  })
  const data = query.data
  const empty = data && ![data.income, data.expenses, data.observed_net_worth, data.available_liquidity].some(v => v != null) && !data.trends?.length
  return <>
    <PageHeader title={t('welcome')} description={t('overviewIntro')} eyebrow={language === 'de' ? 'DEIN FINANZIELLER KOMPASS' : 'YOUR FINANCIAL COMPASS'} action={<Link className="button button-primary" to="/imports"><ArrowDownLeft size={17} />{t('import')}</Link>} />
    <div className="overview-toolbar">
      <div className="segmented" role="group" aria-label={t('date')}>
        {(['month', 'lastmonth', 'quarter', 'sixmonths', 'twelvemonths', 'year', 'custom', 'asof'] as const).map(p => <button key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>{t(p)}</button>)}
      </div>
      <div className="period-controls"><CalendarDays size={16} /><span className="selected-period-range">{rangeLabel}</span>
        <label className="sr-only" htmlFor="overview-currency">{t('currency')}</label>
        <select id="overview-currency" value={currency} onChange={e => setCurrency(e.target.value)}>{[...new Set(['EUR', ...(data?.currencies || []), currency])].map(c => <option key={c}>{c}</option>)}</select>
      </div>
    </div>
    {period === 'custom' && <div className="filter-grid custom-dates">
      <Field label={t('from')}><input type="date" value={from} onChange={e => setFrom(e.target.value)} max={to || undefined} required /></Field>
      <Field label={t('to')}><input type="date" value={to} min={from || undefined} onChange={e => setTo(e.target.value)} required /></Field>
    </div>}
    {period === 'asof' && <><div className="filter-grid custom-dates"><Field label={t('asofDate')}><input type="date" max={today} required value={to} onChange={e => setTo(e.target.value)} /></Field></div><Notice warning>{language === 'de' ? 'Kontostände bis zum Stichtag; Cashflow vom Monatsanfang bis zum Stichtag. Historische Kontozuordnung, Verpflichtungen und Reservierungen sind nicht vollständig versioniert. Aktuelle Zuordnungen sind keine historischen Fakten.' : 'Balances observed on or before the date; cash flow from month start through that date. Historical account inclusion, obligations and allocations are not fully versioned. Current allocations are not historical facts.'}</Notice></>}
    {!validPeriod ? <Notice>{language === 'de' ? 'Bitte wähle einen gültigen Zeitraum.' : 'Please select a valid date range.'}</Notice> : <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={empty} importLink>
      <div className="stats-grid">{[
        { label: 'income' as const, value: data?.income, icon: ArrowDownLeft, color: 'green', note: language === 'de' ? 'Externe Geldeingänge' : 'External money received' },
        { label: 'expenses' as const, value: data?.expenses, icon: ArrowUpRight, color: 'sand', note: language === 'de' ? 'Ohne interne Umbuchungen' : 'Excluding internal transfers' },
        { label: 'surplus' as const, value: data?.surplus, icon: PiggyBank, color: 'purple', note: language === 'de' ? 'Einnahmen minus Ausgaben' : 'Income less expenses' },
        { label: 'netWorth' as const, value: data?.observed_net_worth, icon: Wallet, color: 'blue', note: language === 'de' ? 'Letzte verfügbare Beobachtung' : 'Latest available observation' },
      ].map(({ label, value, icon: Icon, color, note }) => <article className="stat-card" key={label}>
        <div className="stat-top"><span>{t(label)}</span><span className={`stat-icon ${color}`}><Icon size={18} /></span></div>
        <Money value={value} currency={currency} /><p><span className={`tiny-dot ${color}`} />{note}</p>
      </article>)}</div>
      <NewAccountsPrompt />
      <DiskHint language={language} />
      <DataHints warnings={data?.warnings} language={language} />
      <HealthPanel currency={currency} />
      <div className="charts-grid"><CashflowChart trends={data?.trends} currency={currency} /><SpendingChart categories={data?.categories} currency={currency} /></div>
      <div className="bottom-grid">
        <Panel title={t('liquidity')}><Money value={data?.available_liquidity} currency={currency} /><p className="muted small">{t('allocationNote')}</p></Panel>
        <Panel title={t('fixed')}><Money value={data?.fixed_obligations} currency={currency} /><Link to="/buckets" className="text-link">{t('buckets')}<ArrowRight size={15} /></Link></Panel>
        <Panel title={t('savingsRate')}><span className="metric">{data?.savings_rate != null ? `${new Intl.NumberFormat(language === 'de' ? 'de-DE' : 'en-GB', { maximumFractionDigits: 1 }).format(Number(data.savings_rate))} %` : '—'}</span><p className="muted small">{language === 'de' ? 'Auf Basis abgeschlossener Geldbewegungen' : 'Based on completed money movements'}</p></Panel>
      </div>
    </QueryState>}
    <div className="insight-banner">
      <span className="insight-banner-icon"><Sparkles size={22} /></span>
      <div><strong>{language === 'de' ? 'Deine Zahlen erzählen eine Geschichte.' : 'Your numbers tell a story.'}</strong><p>{language === 'de' ? 'Entdecke Muster und stelle Fragen – mit optionaler, kontrollierter KI.' : 'Discover patterns and ask questions — with optional, controlled AI.'}</p></div>
      <Link to="/insights" className="text-link">{t('insights')}<ArrowUpRight size={17} /></Link>
    </div>
    <div className="data-footnote"><ShieldCheck size={14} />{t('balanceWarning')}</div>
  </>
}


// Known notices are explained in German; the permanent "coverage" ones are folded away because the
// Vermögen page and the automatic transfer detection cover them.
const HINTS: Record<string, { de: string; quiet?: boolean }> = {
  'Observed balances may have incomplete coverage; not a complete net worth': { de: 'Kontostände stammen nur aus deinen Importen – Sachwerte und Kredite stehen auf der Seite „Vermögen“.', quiet: true },
  'Debt-service and full asset coverage unavailable': { de: 'Schuldendienst und Sachwerte sind hier nicht enthalten (siehe „Vermögen“).', quiet: true },
  'One-sided transfers excluded; ownership uncertain': { de: 'Einseitige Umbuchungen (Gegenkonto nicht importiert) werden nicht mitgezählt. „Umbuchungen prüfen“ bei den Buchungen paart eigene Konten.', quiet: true },
  'Period contains incomplete months': { de: 'Der Zeitraum enthält angebrochene Monate; deren Summen sind noch nicht vollständig.', quiet: true },
  'Some observed balances are stale': { de: 'Einige Kontostände sind älter als 7 Tage – ein frischer Export aktualisiert sie.' },
  'Some accounts have no observed balance': { de: 'Zu manchen Konten gibt es keinen Kontostand.' },
  'Some account ownership remains unverified': { de: 'Bei manchen Konten ist nicht festgelegt, ob sie dir gehören (Konten → Eigentum).' },
  'Unverified account balances are excluded from available liquidity': { de: 'Konten ohne Eigentumszuordnung zählen nicht zur verfügbaren Liquidität.' },
}
function DataHints({ warnings, language }: { warnings?: string[]; language: string }) {
  if (!warnings?.length) return null
  const de = language === 'de'
  const text = (w: string) => (de && HINTS[w]?.de) || localizeWarning(w, language)
  const loud = warnings.filter(w => !HINTS[w]?.quiet)
  const quiet = warnings.filter(w => HINTS[w]?.quiet)
  return <>
    {loud.map(w => <Notice warning key={w}>{text(w)}</Notice>)}
    {quiet.length > 0 && <details className="muted small"><summary>{de ? `Hinweise zur Datengrundlage (${quiet.length})` : `Data notes (${quiet.length})`}</summary><ul>{quiet.map(w => <li key={w}>{text(w)}</li>)}</ul></details>}
  </>
}

function DiskHint({ language }: { language: string }) {
  const query = useQuery({ queryKey: ['disk'], queryFn: () => api<{ level: string; free_percent: number; free_gb: number }>('/system/disk'), staleTime: 300000 })
  const d = query.data
  if (!d || d.level === 'ok') return null
  const de = language === 'de'
  return <Notice warning>{de ? `Der Speicherplatz wird knapp (${d.free_percent} % bzw. ${d.free_gb} GB frei). Bei vollem Docker-Datenträger kann die Datenbank abstürzen: „docker builder prune -f“ räumt den Build-Cache auf, ein Backup schützt die Daten (docs/operations.md).` : `Disk space is low (${d.free_percent}% / ${d.free_gb} GB free). A full Docker disk can crash the database: "docker builder prune -f" clears the build cache and a backup protects your data (docs/operations.md).`}</Notice>
}
