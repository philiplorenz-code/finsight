import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { Badge, DataTable, Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Overview = {
  year: number; months: string[]; has_rules: boolean
  clients: { name: string; monthly: string[]; total: string; months_paid: number }[]
  expenses: { category: string; monthly: string[]; total: string }[]
  income_monthly: string[]; expense_monthly: string[]; months_without_income: string[]
  totals: { income: string; expenses: string; profit: string; tax_reserve_suggestion: string; tax_reserve_rate: string }
}
const MONTHS_DE = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
const MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function BusinessPage() {
  const { language } = useLocale(); const de = language === 'de'
  const [year, setYear] = useState(new Date().getFullYear())
  const query = useQuery({ queryKey: ['business-overview', year], queryFn: () => api<Overview>(`/business/overview?year=${year}`) })
  const d = query.data
  const short = (v: string) => Number(v) ? formatMoney(v, 'EUR', language).replace(/,\d\d\s/, ' ') : '–'
  const names = de ? MONTHS_DE : MONTHS_EN
  return <>
    <PageHeader title={de ? 'Nebengewerbe' : 'Side business'} description={de ? 'Einnahmen je Auftraggeber, Betriebsausgaben und Monate ohne Zahlungseingang – nach Zahlungsdatum (Zuflussprinzip).' : 'Income per client, business expenses and months without payments – by payment date (cash principle).'}
      action={<div className="badge-row">
        <select aria-label={de ? 'Jahr' : 'Year'} value={year} onChange={e => setYear(Number(e.target.value))}>{[0, 1, 2, 3].map(i => new Date().getFullYear() - i).map(y => <option key={y} value={y}>{y}</option>)}</select>
        <a className="button button-outline" href={`/api/business/euer.csv?year=${year}`} download><Download size={16} />{de ? 'EÜR-Vorschau (CSV)' : 'Cash-basis preview (CSV)'}</a>
      </div>} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{d && <>
      {!d.has_rules && <Notice warning>{de ? 'Noch keine Einkommensregel mit Quelle „Nebengewerbe“. Lege sie in der Wunschliste unter Einkommensquellen an (z. B. „Heise Medien“).' : 'No income rule with source “business” yet. Add one under income sources on the wishlist page.'}</Notice>}
      <div className="stat-grid">
        <div className="detail-stat"><span>{de ? 'Einnahmen' : 'Income'} {d.year}</span><Money value={d.totals.income} /></div>
        <div className="detail-stat"><span>{de ? 'Betriebsausgaben' : 'Business expenses'}</span><Money value={d.totals.expenses} /></div>
        <div className="detail-stat"><span>{de ? 'Gewinn (vereinfacht)' : 'Profit (simplified)'}</span><Money value={d.totals.profit} /></div>
        <div className="detail-stat"><span>{de ? `Rücklage-Vorschlag (${Math.round(Number(d.totals.tax_reserve_rate) * 100)} %)` : `Reserve suggestion (${Math.round(Number(d.totals.tax_reserve_rate) * 100)} %)`}</span><Money value={d.totals.tax_reserve_suggestion} /></div>
      </div>
      {!!d.months_without_income.length && <Notice>{de ? 'Monate ohne Zahlungseingang' : 'Months without payments'}: {d.months_without_income.map(m => names[Number(m.slice(5)) - 1]).join(', ')}</Notice>}
      <Panel title={de ? 'Einnahmen je Auftraggeber' : 'Income per client'}>
        <div className="table-scroll"><DataTable headers={[de ? 'Auftraggeber' : 'Client', ...names, de ? 'Summe' : 'Total']}>
          {d.clients.map(c => <tr key={c.name}><td><strong>{c.name}</strong><div className="small muted">{c.months_paid} {de ? 'Monate mit Zahlung' : 'months paid'}</div></td>{c.monthly.map((v, i) => <td key={i} className={`nowrap small ${Number(v) ? '' : 'muted'}`}>{short(v)}</td>)}<td className="nowrap"><Money value={c.total} /></td></tr>)}
          <tr><td><strong>{de ? 'Summe' : 'Total'}</strong></td>{d.income_monthly.map((v, i) => <td key={i} className="nowrap small"><strong>{short(v)}</strong></td>)}<td className="nowrap"><Money value={d.totals.income} /></td></tr>
        </DataTable></div>
      </Panel>
      <Panel title={de ? 'Betriebsausgaben nach Kategorie' : 'Business expenses by category'} description={de ? 'Über die Regeln für Geschäftsausgaben erkannt (Wunschliste → Nebengewerbe).' : 'Matched by business expense rules.'}>
        {!d.expenses.length ? <p className="muted">{de ? 'Keine Betriebsausgaben erkannt. Software, Hosting oder Fachliteratur fürs Gewerbe? Lege dafür Regeln an.' : 'No business expenses detected. Add rules for software, hosting or literature.'}</p> :
          <div className="table-scroll"><DataTable headers={[de ? 'Kategorie' : 'Category', ...names, de ? 'Summe' : 'Total']}>
            {d.expenses.map(c => <tr key={c.category}><td>{c.category}</td>{c.monthly.map((v, i) => <td key={i} className={`nowrap small ${Number(v) ? '' : 'muted'}`}>{short(v)}</td>)}<td className="nowrap"><Money value={c.total} /></td></tr>)}
          </DataTable></div>}
      </Panel>
      <p className="muted small"><Badge>{de ? 'Hinweis' : 'Note'}</Badge> {de ? 'Vorschau für die Steuerberatung, keine Steuererklärung und keine Steuerberatung. Die CSV öffnet sich in Excel (Semikolon, deutsches Zahlenformat).' : 'Preview for your tax adviser, not a tax return or tax advice.'}</p>
    </>}</QueryState>
  </>
}
