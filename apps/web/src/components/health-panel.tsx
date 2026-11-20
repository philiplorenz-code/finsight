import { useQuery } from '@tanstack/react-query'
import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { label } from '../lib/labels'
import { Money, Notice, Panel } from './ui'

type Alert = { code: string; severity: string; month?: string; category?: string; latest?: string; typical?: string; name?: string; increase?: string; detail?: string }
type Health = {
  currency: string; confidence: string
  metrics: { savings_rate: string | null; emergency_fund_months: string | null; emergency_target_months: string; debt_service_ratio: string | null; spending_volatility: string | null; expected_surplus: string; conservative_surplus: string }
  unavailable: Record<string, string>
  forecast: { start_cash: string; months: { month: string; expected: string; cautious: string }[] }
  alerts: Alert[]
}

function alertText(a: Alert, de: boolean, cur: string, lang: string): string {
  const m = (v?: string) => formatMoney(v ?? '0', cur, lang === 'de' ? 'de' : 'en')
  switch (a.code) {
    case 'cash_underfunded': return de ? `Im vorsichtigen Fall reicht dein freies Geld ab ${a.month} nicht mehr.` : `In the cautious case your free cash runs out from ${a.month}.`
    case 'emergency_fund_low': return de ? 'Die Notfallreserve deckt weniger als 3 Monatsausgaben.' : 'Your emergency fund covers less than 3 months of spending.'
    case 'negative_surplus': return de ? 'Im Schnitt gibst du mehr aus, als du einnimmst.' : 'On average you spend more than you earn.'
    case 'volatile_spending': return de ? 'Deine Ausgaben schwanken stark von Monat zu Monat.' : 'Your spending varies strongly from month to month.'
    case 'category_anomaly': return de ? `${a.category}: letzter Monat ${m(a.latest)} statt üblich ${m(a.typical)}.` : `${a.category}: last month ${m(a.latest)} instead of the usual ${m(a.typical)}.`
    case 'price_increase': return de ? `${a.name} ist teurer geworden (+${m(a.increase)} pro Abbuchung).` : `${a.name} became more expensive (+${m(a.increase)} per charge).`
    case 'data_quality': return de ? 'Die Datenlage hat Lücken oder ist veraltet; die Werte sind mit Vorsicht zu lesen.' : 'The data has gaps or is stale; read the figures with care.'
    default: return a.code
  }
}

export function HealthPanel({ currency }: { currency: string }) {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['health-metrics', currency], queryFn: () => api<Health>(`/health-metrics?currency=${currency}`) })
  const d = query.data
  if (!d || !d.metrics || !Array.isArray(d.alerts)) return null
  const pct = (v: string | null) => v == null ? '—' : `${(Number(v) * 100).toFixed(0)} %`
  const months = (v: string | null) => v == null ? '—' : `${Number(v).toFixed(1)} ${de ? 'Mon.' : 'mo.'}`
  const stat = (label: string, value: string, key: string) => <div className="detail-stat" key={key} title={d.unavailable[key] ? (de ? 'Nicht berechenbar: Datengrundlage fehlt' : 'Unavailable: missing input data') : undefined}><span>{label}</span><strong>{value}</strong></div>
  const chart = d.forecast.months.map(p => ({ month: p.month, expected: Number(p.expected), cautious: Number(p.cautious) }))
  return <Panel title={de ? 'Finanz-Check' : 'Financial check'} description={de ? 'Kennzahlen, Prognose und Auffälligkeiten aus deinen Daten. Nicht berechenbare Werte bleiben leer, statt geschätzt zu werden.' : 'Metrics, forecast and anomalies from your data. Values without enough input stay empty instead of being guessed.'}>
    {d.alerts.map((a, i) => <Notice warning={a.severity === 'high' || a.severity === 'medium'} key={i}>{alertText(a, de, d.currency, language)}</Notice>)}
    <div className="stat-grid">
      {stat(de ? 'Sparquote' : 'Savings rate', pct(d.metrics.savings_rate), 'savings_rate')}
      {stat(de ? 'Notfallreserve' : 'Emergency fund', months(d.metrics.emergency_fund_months), 'emergency_fund_months')}
      {stat(de ? 'Schuldendienst / Einkommen' : 'Debt service / income', pct(d.metrics.debt_service_ratio), 'debt_service_ratio')}
      {stat(de ? 'Ausgaben-Schwankung' : 'Spending volatility', pct(d.metrics.spending_volatility), 'spending_volatility')}
    </div>
    {chart.length > 0 && <>
      <h3 className="small muted">{de ? 'Prognose freies Geld (6 Monate)' : 'Free cash forecast (6 months)'}</h3>
      <div className="forecast-container" role="img" aria-label="cash forecast"><ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chart} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis axisLine={false} tickLine={false} width={64} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickFormatter={v => formatMoney(String(v), d.currency, language)} />
          <Tooltip contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12 }} formatter={(v) => formatMoney(String(v), d.currency, language)} />
          <Area dataKey="expected" name={de ? 'Erwartet' : 'Expected'} stroke="#287a68" fill="#287a68" fillOpacity={0.15} />
          <Line dataKey="cautious" name={de ? 'Vorsichtig' : 'Cautious'} stroke="#b4503c" strokeDasharray="4 3" dot={false} />
        </AreaChart>
      </ResponsiveContainer></div>
      <p className="muted small">{de ? 'Startwert' : 'Start'}: <Money value={d.forecast.start_cash} currency={d.currency} /> · {de ? 'Konfidenz' : 'Confidence'}: {label('confidence', d.confidence, de ? 'de' : 'en')}</p>
    </>}
  </Panel>
}
