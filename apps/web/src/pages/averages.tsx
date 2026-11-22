import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { label } from '../lib/labels'
import { DataTable, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Source = { monthly_average: string; monthly_current?: string; monthly_lower_quartile: string; months_with_income: number; share: string }
type Data = {
  baseline: { currency: string; months_used: number; confidence: string; monthly_income: string; monthly_consumption: string; monthly_tax: string
    expected_surplus: string; conservative_surplus: string; income_sources: Record<string, Source>
    business?: { income_monthly: string; income_weak_quarter: string; expenses_monthly: string; profit_monthly: string } }
}
type Analytics = { savings: { categories: { category: string; average: string; recent: string; prior: string; fixed: boolean }[]; fixed_monthly: string; variable_monthly: string } }

/** All averages in one place, for analysis. The other pages show concrete monthly figures instead. */
export default function AveragesPage() {
  const { language } = useLocale(); const de = language === 'de'
  const wish = useQuery({ queryKey: ['wishlist'], queryFn: () => api<Data>('/wishlist') })
  const analytics = useQuery({ queryKey: ['analytics', 'EUR'], queryFn: () => api<Analytics>('/analytics?currency=EUR') })
  const b = wish.data?.baseline
  const money = (v?: string | null) => formatMoney(v ?? '0', b?.currency ?? 'EUR', language)
  const names: Record<string, string> = { employment: de ? 'Gehalt' : 'Salary', business: de ? 'Nebengewerbe' : 'Side business', other: de ? 'Sonstiges' : 'Other' }
  return <>
    <PageHeader title={de ? 'Durchschnitte' : 'Averages'} description={de ? 'Mittelwerte für Analysen. Für Planung und Übersicht zeigt FinSight dir die konkreten Monatswerte; hier siehst du, wie sich die Zahlen über die Zeit verhalten.' : 'Averages for analysis. Elsewhere FinSight shows concrete monthly figures.'} />
    <QueryState pending={wish.isPending} error={wish.error} retry={wish.refetch}>{b && <>
      <Notice>{de ? `Grundlage: ${b.months_used} vollständige Monate · Datenqualität ${label('confidence', b.confidence, language)}.` : `Based on ${b.months_used} complete months · confidence ${label('confidence', b.confidence, language)}.`}</Notice>
      <Panel title={de ? 'Monatliche Durchschnitte' : 'Monthly averages'}>
        <div className="stat-grid">
          <div className="detail-stat"><span>{de ? 'Einnahmen Ø' : 'Income avg.'}</span><strong>{money(b.monthly_income)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Ausgaben Ø' : 'Spending avg.'}</span><strong>{money(b.monthly_consumption)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Steuerrücklage Ø' : 'Tax reserve avg.'}</span><strong>{money(b.monthly_tax)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Überschuss erwartet' : 'Expected surplus'}</span><strong>{money(b.expected_surplus)}</strong><small className="muted">{de ? 'Planwert für Wunschliste und Prognose' : 'planning value'}</small></div>
          <div className="detail-stat"><span>{de ? 'Überschuss vorsichtig' : 'Cautious surplus'}</span><strong>{money(b.conservative_surplus)}</strong><small className="muted">{de ? 'schwache Monate, schwaches Nebengewerbe' : 'weak months'}</small></div>
        </div>
      </Panel>
      <Panel title={de ? 'Einkommensquellen' : 'Income sources'}>
        <DataTable headers={[de ? 'Quelle' : 'Source', de ? 'Ø pro Monat' : 'Avg./month', de ? 'Aktuell (letzter Monat)' : 'Current (last month)', de ? 'Schwaches Viertel' : 'Weak quarter', de ? 'Monate mit Zahlung' : 'Months paid', de ? 'Anteil' : 'Share']}>
          {Object.entries(b.income_sources).map(([k, s]) => <tr key={k}><td>{names[k] ?? k}</td><td className="num">{money(s.monthly_average)}</td><td className="num">{money(s.monthly_current ?? s.monthly_average)}</td><td className="num">{money(s.monthly_lower_quartile)}</td><td className="num">{s.months_with_income}</td><td className="num">{Math.round(Number(s.share) * 100)} %</td></tr>)}
        </DataTable>
      </Panel>
      {b.business && <Panel title={de ? 'Nebengewerbe im Schnitt' : 'Side business on average'}>
        <div className="stat-grid">
          <div className="detail-stat"><span>{de ? 'Einnahmen Ø' : 'Income avg.'}</span><strong>{money(b.business.income_monthly)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Schwaches Viertel' : 'Weak quarter'}</span><strong>{money(b.business.income_weak_quarter)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Ausgaben Ø' : 'Expenses avg.'}</span><strong>{money(b.business.expenses_monthly)}</strong></div>
          <div className="detail-stat"><span>{de ? 'Gewinn Ø' : 'Profit avg.'}</span><strong>{money(b.business.profit_monthly)}</strong></div>
        </div>
      </Panel>}
      {analytics.data && <Panel title={de ? 'Kategorien im Schnitt' : 'Categories on average'} description={de ? `Fest ${money(analytics.data.savings.fixed_monthly)} · variabel ${money(analytics.data.savings.variable_monthly)} pro Monat im Schnitt.` : ''}>
        <div className="table-scroll"><DataTable headers={[de ? 'Kategorie' : 'Category', de ? 'Ø pro Monat' : 'Avg./month', de ? 'Früher typisch' : 'Earlier', de ? 'Zuletzt typisch' : 'Recent', de ? 'Art' : 'Type']}>
          {analytics.data.savings.categories.map(c => <tr key={c.category}><td>{c.category}</td><td className="num">{money(c.average)}</td><td className="num muted">{money(c.prior)}</td><td className="num">{money(c.recent)}</td><td className="small">{c.fixed ? (de ? 'fest' : 'fixed') : (de ? 'variabel' : 'variable')}</td></tr>)}
        </DataTable></div>
      </Panel>}
    </>}</QueryState>
  </>
}
