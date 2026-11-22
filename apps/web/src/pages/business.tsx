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
  pnl: Pnl
}
type PnlRow = { month: string; gross: string; vat: string; net_revenue: string; expenses: string; ebitda: string; tax_adviser: string; profit_before_tax: string; income_tax_reserve: string; left: string; moved_vat: string; moved_income_tax: string; moved_adviser: string; paid_vat: string; paid_income_tax: string }
type Pnl = { vat_rate: string; income_tax_rate: string; months: PnlRow[]; total: Omit<PnlRow, 'month'>; net_margin?: string | null; reserve_gap: { vat: string; income_tax: string }; pots_found: string[] }
const MONTHS_DE = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
const MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function BusinessPage() {
  const { language } = useLocale(); const de = language === 'de'
  const [year, setYear] = useState(new Date().getFullYear())
  const [vat, setVat] = useState(() => { try { return localStorage.getItem('finsight-vat-rate') ?? '0.19' } catch { return '0.19' } })
  const chooseVat = (v: string) => { setVat(v); try { localStorage.setItem('finsight-vat-rate', v) } catch { /* ignore */ } }
  const query = useQuery({ queryKey: ['business-overview', year, vat], queryFn: () => api<Overview>(`/business/overview?year=${year}&vat_rate=${vat}`) })
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
        <div className="detail-stat"><span>{de ? 'Überschuss brutto (vor Steuern)' : 'Gross surplus (before tax)'}</span><Money value={d.totals.profit} /></div>
        <div className="detail-stat"><span>{de ? `Rücklage-Vorschlag (${Math.round(Number(d.totals.tax_reserve_rate) * 100)} %)` : `Reserve suggestion (${Math.round(Number(d.totals.tax_reserve_rate) * 100)} %)`}</span><Money value={d.totals.tax_reserve_suggestion} /></div>
      </div>
      <PnlPanel pnl={d.pnl} de={de} names={names} vat={vat} onVat={chooseVat} />
      {!!d.months_without_income.length && <Notice>{de ? 'Monate ohne Zahlungseingang' : 'Months without payments'}: {d.months_without_income.map(m => names[Number(m.slice(5)) - 1]).join(', ')}</Notice>}
      <Panel title={de ? 'Einnahmen je Auftraggeber' : 'Income per client'}>
        <ul className="client-cards only-phone">{d.clients.map(c => <li key={c.name}>
          <div className="open-head"><strong>{c.name}</strong><Money value={c.total} /></div>
          <div className="chip-row">{c.monthly.map((v, i) => Number(v) ? <span key={i} className="chip">{names[i]} {short(v)}</span> : null)}</div>
        </li>)}</ul>
        <div className="table-scroll only-wide"><DataTable headers={[de ? 'Auftraggeber' : 'Client', ...names, de ? 'Summe' : 'Total']}>
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

function PnlPanel({ pnl, de, names, vat, onVat }: { pnl: Pnl; de: boolean; names: string[]; vat: string; onVat: (v: string) => void }) {
  const t = pnl.total
  const steps: [string, string, 'plus' | 'minus' | 'sum'][] = [
    [de ? 'Einnahmen brutto' : 'Gross income', t.gross, 'sum'],
    [de ? `− Umsatzsteuer (${Math.round(Number(pnl.vat_rate) * 100)} %)` : `− VAT (${Math.round(Number(pnl.vat_rate) * 100)} %)`, t.vat, 'minus'],
    [de ? '= Umsatz netto' : '= Net revenue', t.net_revenue, 'sum'],
    [de ? '− Betriebsausgaben' : '− Business expenses', t.expenses, 'minus'],
    [de ? '= EBITDA (= EBIT, keine Abschreibungen erfasst)' : '= EBITDA (= EBIT, no depreciation tracked)', t.ebitda, 'sum'],
    [de ? '− Steuerberater' : '− Tax adviser', t.tax_adviser, 'minus'],
    [de ? '= Gewinn vor Einkommensteuer' : '= Profit before income tax', t.profit_before_tax, 'sum'],
    [de ? `− Einkommensteuer-Rücklage (${Math.round(Number(pnl.income_tax_rate) * 100)} %)` : `− Income tax reserve (${Math.round(Number(pnl.income_tax_rate) * 100)} %)`, t.income_tax_reserve, 'minus'],
    [de ? '= Bleibt dir netto' : '= Left for you (net)', t.left, 'sum'],
  ]
  const max = Math.max(1, Number(t.gross))
  return <Panel title={de ? 'Brutto bis netto: was hängen bleibt' : 'Gross to net: what is left'} description={de ? 'Umsatzsteuer und Einkommensteuer gehören nicht dir. Rücklage-Soll gegen das, was du wirklich in deine Steuertöpfe verschoben hast.' : 'VAT and income tax are not yours. Required reserves against what you actually moved into your tax pots.'}
    action={<select aria-label={de ? 'Umsatzsteuersatz' : 'VAT rate'} value={vat} onChange={e => onVat(e.target.value)}><option value="0.19">19 % USt</option><option value="0.07">7 % USt</option><option value="0">{de ? '0 % (Kleinunternehmer)' : '0 % (small business)'}</option></select>}>
    <div className="pnl-steps">{steps.map(([label, value, kind]) => <div key={label} className={`pnl-step ${kind}`}>
      <span>{label}</span><span className="pnl-track"><span style={{ width: `${Math.max(1, Math.abs(Number(value)) / max * 100)}%` }} /></span><Money value={kind === 'minus' ? String(-Number(value)) : value} />
    </div>)}</div>
    <div className="stat-grid">
      <div className="detail-stat"><span>{de ? 'Nettomarge (bleibt / brutto)' : 'Net margin (left / gross)'}</span><strong>{pnl.net_margin != null ? `${(Number(pnl.net_margin) * 100).toFixed(0)} %` : '—'}</strong></div>
      <div className="detail-stat"><span>{de ? 'USt in Topf verschoben' : 'VAT moved to pot'}</span><Money value={t.moved_vat} /><small className={Number(pnl.reserve_gap.vat) > 0.5 ? 'negative' : 'muted'}>{Number(pnl.reserve_gap.vat) > 0.5 ? (de ? 'fehlen ' : 'missing ') : (de ? 'Puffer ' : 'buffer ')}<Money value={String(Math.abs(Number(pnl.reserve_gap.vat)))} /></small></div>
      <div className="detail-stat"><span>{de ? 'ESt in Topf verschoben' : 'Income tax moved to pot'}</span><Money value={t.moved_income_tax} /><small className={Number(pnl.reserve_gap.income_tax) > 0.5 ? 'negative' : 'muted'}>{Number(pnl.reserve_gap.income_tax) > 0.5 ? (de ? 'fehlen ' : 'missing ') : (de ? 'Puffer ' : 'buffer ')}<Money value={String(Math.abs(Number(pnl.reserve_gap.income_tax)))} /></small></div>
      <div className="detail-stat"><span>{de ? 'An Finanzamt gezahlt (aus Töpfen)' : 'Paid to tax office (from pots)'}</span><Money value={String(Number(t.paid_vat) + Number(t.paid_income_tax))} /></div>
    </div>
    {!pnl.pots_found.length && <Notice>{de ? 'Keine Steuertöpfe erkannt. Töpfe mit „Umsatzsteuer“, „Einkommensteuer“ oder „Steuerberater“ im Namen werden automatisch zugeordnet.' : 'No tax pots found. Pots named with “Umsatzsteuer”, “Einkommensteuer” or “Steuerberater” are matched automatically.'}</Notice>}
    <details><summary>{de ? 'Monat für Monat' : 'Month by month'}</summary><div className="table-scroll"><DataTable headers={[de ? 'Monat' : 'Month', de ? 'Brutto' : 'Gross', 'USt', de ? 'Netto' : 'Net', de ? 'Ausgaben' : 'Expenses', 'EBITDA', de ? 'Steuerberater' : 'Adviser', de ? 'ESt-Rücklage' : 'Tax reserve', de ? 'Bleibt' : 'Left', de ? 'In Töpfe' : 'To pots']}>
      {pnl.months.filter(m => Number(m.gross) || Number(m.expenses) || Number(m.tax_adviser) || Number(m.moved_vat) || Number(m.moved_income_tax)).map(m => <tr key={m.month}><td>{names[Number(m.month.slice(5)) - 1]}</td>
        {[m.gross, m.vat, m.net_revenue, m.expenses, m.ebitda, m.tax_adviser, m.income_tax_reserve, m.left].map((v, i) => <td key={i} className="nowrap small"><Money value={v} /></td>)}
        <td className="nowrap small"><Money value={String(Number(m.moved_vat) + Number(m.moved_income_tax) + Number(m.moved_adviser))} /></td></tr>)}
    </DataTable></div></details>
    <p className="muted small">{de ? 'Vereinfachung: Vorsteuer auf Ausgaben ist nicht abgezogen, die Einkommensteuer ist mit dem Rücklagesatz geschätzt. Keine Steuerberatung.' : 'Simplified: input VAT on expenses is not deducted; income tax is estimated with the reserve rate. Not tax advice.'}</p>
  </Panel>
}
