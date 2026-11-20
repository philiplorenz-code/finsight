import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
const CONF: Record<string, [string, string]> = { low: ['niedrig', 'low'], medium: ['mittel', 'medium'], high: ['hoch', 'high'] }
import { Notice, Panel } from './ui'
import { ZoomChart } from './zoom-chart'

type Forecast = {
  currency: string; confidence: string; start: { month: string; cash: string; net_worth: string }
  monthly: { expected_surplus: string; cautious_surplus: string }
  loans: { name: string; paid_off?: string | null; payment: string }[]
  months: { month: string; cash_expected: string; cash_cautious: string; net_worth_expected: string; net_worth_cautious: string; debt: string }[]
}

export function ForecastPanel({ currency = 'EUR' }: { currency?: string }) {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['forecast', currency], queryFn: () => api<Forecast>(`/forecast?months=24&currency=${currency}`) })
  const d = query.data
  if (!d) return null
  const last = d.months[d.months.length - 1]
  const money = (v: string) => formatMoney(v, currency, language)
  return <Panel title={de ? 'Prognose: Geld und Vermögen (24 Monate)' : 'Forecast: money and net worth (24 months)'}
    description={de ? `Erwartet mit ${money(d.monthly.expected_surplus)} Überschuss pro Monat, vorsichtig mit ${money(d.monthly.cautious_surplus)}. Konfidenz: ${(CONF[d.confidence] ?? [d.confidence, d.confidence])[de ? 0 : 1]}.` : `Expected with ${money(d.monthly.expected_surplus)} surplus per month, cautious with ${money(d.monthly.cautious_surplus)}. Confidence: ${(CONF[d.confidence] ?? [d.confidence, d.confidence])[de ? 0 : 1]}.`}>
    <ZoomChart label={de ? 'Prognose' : 'Forecast'} currency={currency} x="month" height={280}
      series={[{ key: 'nw_e', name: de ? 'Vermögen erwartet' : 'Net worth expected', color: '#2d8b72' },
               { key: 'nw_c', name: de ? 'Vermögen vorsichtig' : 'Net worth cautious', color: '#91b7a5', fill: false },
               { key: 'cash_e', name: de ? 'Geld erwartet' : 'Cash expected', color: '#5b8fd1', fill: false },
               { key: 'cash_c', name: de ? 'Geld vorsichtig' : 'Cash cautious', color: '#d4ab70', fill: false }]}
      data={d.months.map(m => ({ month: m.month, nw_e: Number(m.net_worth_expected), nw_c: Number(m.net_worth_cautious), cash_e: Number(m.cash_expected), cash_c: Number(m.cash_cautious) }))} />
    {last && <div className="stat-grid forecast-stats">
      <div className="detail-stat"><span>{de ? `Vermögen ${last.month}` : `Net worth ${last.month}`}</span><strong>{money(last.net_worth_expected)}</strong><small className="muted">{de ? 'vorsichtig' : 'cautious'} {money(last.net_worth_cautious)}</small></div>
      <div className="detail-stat"><span>{de ? `Geld ${last.month}` : `Cash ${last.month}`}</span><strong>{money(last.cash_expected)}</strong><small className="muted">{de ? 'vorsichtig' : 'cautious'} {money(last.cash_cautious)}</small></div>
      {d.loans.map(l => <div className="detail-stat" key={l.name}><span>{l.name}</span><strong>{l.paid_off ? (de ? `abbezahlt ${l.paid_off}` : `paid off ${l.paid_off}`) : (de ? 'nicht absehbar' : 'no payoff date')}</strong><small className="muted">{de ? 'danach frei' : 'then freed'}: {money(l.payment)}/{de ? 'Monat' : 'month'}</small></div>)}
    </div>}
    <Notice>{de ? 'Annahmen: Überschuss wie in deinem Durchschnitt, Sachwerte bleiben gleich, Kreditraten sind schon in den Ausgaben und werden nach der Tilgung frei. Keine Anlageberatung.' : 'Assumptions: surplus as on average, assets stay flat, loan payments are already in spending and are freed after payoff. Not investment advice.'}</Notice>
  </Panel>
}
