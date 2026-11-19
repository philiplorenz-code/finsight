import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { Money, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Series = {
  months: string[]; income: Record<string, string[]>; expenses: string[]; business_expenses?: string[]; tax: string[]; surplus: string[]
  categories: Record<string, string[]>; other_categories: string[]; top_merchants: { merchant: string; total: string }[]
}
type SavingsCat = { category: string; average: string; recent: string; prior: string; delta: string; share: string; fixed: boolean; months_with_spend: number }
type Savings = {
  enough_data: boolean; categories: SavingsCat[]; fixed_monthly: string; variable_monthly: string; fixed_by_month: string[]; variable_by_month: string[]
  potential_monthly: string; potential_categories: string[]; recurring_monthly: string
  recurring: { name: string; monthly_cost: string; period: string; price_change: string | null; source: string }[]
}
type Analytics = { currency: string; months_used: number; data_through: string | null; series: Series; savings: Savings }

const palette = ['#287a68', '#d5aa64', '#7a8c96', '#91b7a5', '#c8b7a8', '#bcccbf', '#b5654f', '#5b7fa6', '#9b8fb5']
const SOURCE_COLORS: Record<string, string> = { employment: '#287a68', business: '#d5aa64', other: '#7a8c96' }
const tooltipStyle = { background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12 }
const axis = { fill: 'var(--muted)', fontSize: 11 }
const sum = (values: number[]) => values.reduce((a, b) => a + b, 0)

function ChartBox({ label, children }: { label: string; children: React.ReactElement }) {
  return <div className="chart-container" role="img" aria-label={label}><ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer></div>
}

export default function AnalysisPage() {
  const { t, language } = useLocale()
  const query = useQuery({ queryKey: ['analytics'], queryFn: () => api<Analytics>('/analytics') })
  const data = query.data
  const view = useMemo(() => {
    if (!data) return null
    const s = data.series
    const num = (v: string[]) => v.map(Number)
    const months = s.months.map(m => m.slice(0, 7))
    const income = months.map((_, i) => sum(Object.values(s.income).map(v => Number(v[i]))))
    const expenses = num(s.expenses)
    const tax = num(s.tax)
    const surplus = num(s.surplus)
    let running = 0
    const rows = months.map((month, i) => {
      running += surplus[i]
      return {
        month, income: income[i], expenses: expenses[i], bizIncome: Number(s.income.business?.[i] ?? 0), bizExpenses: Number(s.business_expenses?.[i] ?? 0), bizProfit: Number(s.income.business?.[i] ?? 0) - Number(s.business_expenses?.[i] ?? 0), tax: tax[i], surplus: surplus[i], cumulative: running,
        rate: income[i] > 0 ? Math.round((surplus[i] / income[i]) * 1000) / 10 : 0,
        ...Object.fromEntries(Object.entries(s.income).map(([k, v]) => [`src_${k}`, Number(v[i])])),
        ...Object.fromEntries(Object.entries(s.categories).map(([k, v]) => [`cat_${k}`, Number(v[i])])),
        other_cat: Number(s.other_categories[i]),
      }
    })
    return { rows, categories: Object.keys(s.categories), average: months.length ? sum(surplus) / months.length : 0, merchants: s.top_merchants.map(m => ({ name: m.merchant, total: Number(m.total) })) }
  }, [data])
  const money = (v: unknown) => formatMoney(String(v), data?.currency ?? 'EUR', language)
  const common = { margin: { left: -10, right: 12, top: 16, bottom: 0 } }
  const grid = <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
  const xAxis = <XAxis dataKey="month" axisLine={false} tickLine={false} tick={axis} />
  const yAxis = <YAxis axisLine={false} tickLine={false} tick={axis} />
  const tip = <Tooltip formatter={money} contentStyle={tooltipStyle} />
  const legend = <Legend wrapperStyle={{ fontSize: 12 }} />
  const srcName = (k: string) => t(`src_${k}` as never)
  return <>
    <PageHeader title={t('analysis')} description={t('analysisIntro')} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>
      {data && view && (view.rows.length === 0 ? <Notice>{t('noChart')}</Notice> : <div className="charts-stack">
        <Panel title={t('chIncomeSources')}>
          <ChartBox label={t('chIncomeSources')}><BarChart data={view.rows} {...common}>{grid}{xAxis}{yAxis}{tip}{legend}
            {Object.keys(SOURCE_COLORS).map(k => <Bar key={k} isAnimationActive={false} stackId="inc" name={srcName(k)} dataKey={`src_${k}`} fill={SOURCE_COLORS[k]} />)}
          </BarChart></ChartBox>
        </Panel>
        {view.rows.some(r => r.bizExpenses > 0 || r.bizIncome > 0) && <Panel title={language === 'de' ? 'Gewerbe: Einnahmen, Ausgaben und Gewinn' : 'Business: income, expenses and profit'}>
          <ChartBox label="business"><ComposedChart data={view.rows} {...common}>{grid}{xAxis}{yAxis}{tip}{legend}
            <Bar isAnimationActive={false} name={t('src_business')} dataKey="src_business" fill="#d5aa64" />
            <Bar isAnimationActive={false} name={language === 'de' ? 'Gewerbe-Ausgaben' : 'Business expenses'} dataKey="bizExpenses" fill="#b5654f" />
            <Line isAnimationActive={false} type="monotone" name={language === 'de' ? 'Gewinn' : 'Profit'} dataKey="bizProfit" stroke="#287a68" strokeWidth={2.5} dot={false} />
          </ComposedChart></ChartBox>
        </Panel>}
        <Panel title={t('chIncomeVsOut')}>
          <ChartBox label={t('chIncomeVsOut')}><LineChart data={view.rows} {...common}>{grid}{xAxis}{yAxis}{tip}{legend}
            <Line isAnimationActive={false} type="monotone" name={t('income')} dataKey="income" stroke="#287a68" strokeWidth={2.5} dot={false} />
            <Line isAnimationActive={false} type="monotone" name={t('chSpending')} dataKey="expenses" stroke="#d5aa64" strokeWidth={2.5} dot={false} />
            <Line isAnimationActive={false} type="monotone" name={t('chTax')} dataKey="tax" stroke="#7a8c96" strokeWidth={2} strokeDasharray="4 4" dot={false} />
          </LineChart></ChartBox>
        </Panel>
        <Panel title={t('chSurplus')}>
          <ChartBox label={t('chSurplus')}><BarChart data={view.rows} {...common}>{grid}{xAxis}{yAxis}{tip}
            <ReferenceLine y={0} stroke="var(--muted)" />
            <ReferenceLine y={view.average} stroke="#7a8c96" strokeDasharray="4 4" label={{ value: t('chSurplusAvg'), fill: 'var(--muted)', fontSize: 11, position: 'insideTopRight' }} />
            <Bar isAnimationActive={false} name={t('chSurplus')} dataKey="surplus">{view.rows.map(r => <Cell key={r.month} fill={r.surplus >= 0 ? '#287a68' : '#b5654f'} />)}</Bar>
          </BarChart></ChartBox>
        </Panel>
        <Panel title={t('chSavingsRate')}>
          <ChartBox label={t('chSavingsRate')}><LineChart data={view.rows} {...common}>{grid}{xAxis}{yAxis}<Tooltip formatter={v => `${v} %`} contentStyle={tooltipStyle} />
            <ReferenceLine y={0} stroke="var(--muted)" />
            <Line isAnimationActive={false} type="monotone" name={t('chSavingsRate')} dataKey="rate" stroke="#5b7fa6" strokeWidth={2.5} />
          </LineChart></ChartBox>
        </Panel>
        <Panel title={t('chCumulative')}>
          <ChartBox label={t('chCumulative')}><AreaChart data={view.rows} {...common}>{grid}{xAxis}{yAxis}{tip}
            <ReferenceLine y={0} stroke="var(--muted)" />
            <Area isAnimationActive={false} type="monotone" name={t('chCumulative')} dataKey="cumulative" stroke="#287a68" strokeWidth={2.5} fill="#287a68" fillOpacity={0.15} />
          </AreaChart></ChartBox>
        </Panel>
        <Panel title={t('chCategories')}>
          <ChartBox label={t('chCategories')}><BarChart data={view.rows} {...common}>{grid}{xAxis}{yAxis}{tip}{legend}
            {view.categories.map((c, i) => <Bar key={c} isAnimationActive={false} stackId="cat" name={c} dataKey={`cat_${c}`} fill={palette[i % palette.length]} />)}
            <Bar isAnimationActive={false} stackId="cat" name={t('chOtherCategories')} dataKey="other_cat" fill="#cfd6d2" />
          </BarChart></ChartBox>
        </Panel>
        {data.savings && <SavingsSection savings={data.savings} months={view.rows.map(r => r.month)} currency={data.currency} de={language === 'de'} money={money} grid={grid} xAxis={xAxis} yAxis={yAxis} tip={tip} legend={legend} common={common} />}
        <Panel title={t('chTopMerchants')}>
          <div className="chart-container tall" role="img" aria-label={t('chTopMerchants')}><ResponsiveContainer width="100%" height="100%">
            <BarChart data={view.merchants} layout="vertical" margin={{ left: 20, right: 16, top: 8, bottom: 0 }}>{grid}
              <XAxis type="number" axisLine={false} tickLine={false} tick={axis} /><YAxis type="category" dataKey="name" width={110} axisLine={false} tickLine={false} tick={axis} />{tip}
              <Bar isAnimationActive={false} name={t('chSpending')} dataKey="total" fill="#d5aa64" radius={[0, 6, 6, 0]} />
            </BarChart></ResponsiveContainer></div>
        </Panel>
      </div>)}
    </QueryState>
  </>
}


type SectionProps = { savings: Savings; months: string[]; currency: string; de: boolean; money: (v: unknown) => string; grid: React.ReactElement; xAxis: React.ReactElement; yAxis: React.ReactElement; tip: React.ReactElement; legend: React.ReactElement; common: object }
function SavingsSection({ savings, months, currency, de, grid, xAxis, yAxis, tip, legend, common }: SectionProps) {
  const rows = months.map((month, i) => ({ month, fixed: Number(savings.fixed_by_month[i]), variable: Number(savings.variable_by_month[i]) }))
  const trend = savings.categories.filter(c => !c.fixed).slice(0, 8).map(c => ({ name: c.category, prior: Number(c.prior), recent: Number(c.recent) }))
  const rising = savings.categories.filter(c => Number(c.delta) > 0 && c.months_with_spend >= 4 && !c.fixed).sort((a, b) => Number(b.delta) - Number(a.delta)).slice(0, 5)
  return <>
    <Panel title={de ? 'Sparpotenzial' : 'Savings potential'} description={de ? 'Rechnerisch aus deinen eigenen Zahlen, ohne Prognose: fest = fast jeden Monat in ähnlicher Höhe, variabel = der Rest.' : 'Plain arithmetic on your own data: fixed = about the same almost every month, variable = the rest.'}>
      <div className="stat-grid">
        <div className="detail-stat"><span>{de ? 'Fixkosten pro Monat' : 'Fixed per month'}</span><Money value={savings.fixed_monthly} currency={currency} /></div>
        <div className="detail-stat"><span>{de ? 'Variable Ausgaben pro Monat' : 'Variable per month'}</span><Money value={savings.variable_monthly} currency={currency} /></div>
        <div className="detail-stat"><span>{de ? 'Wiederkehrende Verträge' : 'Recurring contracts'}</span><Money value={savings.recurring_monthly} currency={currency} /></div>
        <div className="detail-stat"><span>{de ? 'Mehrausgaben gegenüber früher' : 'Extra vs. before'}</span><Money value={savings.potential_monthly} currency={currency} /></div>
      </div>
      {savings.enough_data
        ? <p className="muted">{Number(savings.potential_monthly) > 0
          ? (de ? `Wenn ${rising.map(r => r.category).join(', ')} wieder auf den früheren Schnitt zurückgehen, bleiben rechnerisch pro Monat mehr übrig (Spalte „Mehrausgaben“). Einmalige Ausreißer sind ausgeschlossen: Es zählen nur Kategorien mit Ausgaben in mindestens 4 Monaten.` : 'If the rising categories return to their earlier average, this much more is left each month.')
          : (de ? 'Keine Kategorie ist zuletzt auffällig gestiegen.' : 'No category has risen noticeably.')}</p>
        : <Notice>{de ? 'Für Trends braucht es mindestens 6 vollständige Monate.' : 'Trends need at least 6 complete months.'}</Notice>}
    </Panel>
    <Panel title={de ? 'Fixkosten und variable Ausgaben' : 'Fixed and variable spending'}>
      <ChartBox label="fixed and variable"><BarChart data={rows} {...common}>{grid}{xAxis}{yAxis}{tip}{legend}
        <Bar isAnimationActive={false} stackId="fv" name={de ? 'Fix' : 'Fixed'} dataKey="fixed" fill="#287a68" />
        <Bar isAnimationActive={false} stackId="fv" name={de ? 'Variabel' : 'Variable'} dataKey="variable" fill="#d5aa64" />
      </BarChart></ChartBox>
    </Panel>
    {savings.enough_data && trend.length > 0 && <Panel title={de ? 'Kategorien: letzte 3 Monate gegen früher' : 'Categories: last 3 months vs before'} description={de ? 'Typischer Monat (Median), nur variable Kategorien; Lücken und einzelne Ausreißer verzerren das nicht.' : 'Typical month (median), variable categories only; gaps and single spikes do not distort it.'}>
      <div className="chart-container tall" role="img" aria-label="category trend"><ResponsiveContainer width="100%" height="100%">
        <BarChart data={trend} layout="vertical" margin={{ left: 20, right: 16, top: 8, bottom: 0 }}>{grid}
          <XAxis type="number" axisLine={false} tickLine={false} tick={axis} /><YAxis type="category" dataKey="name" width={120} axisLine={false} tickLine={false} tick={axis} />{tip}{legend}
          <Bar isAnimationActive={false} name={de ? 'Früher' : 'Before'} dataKey="prior" fill="#bcccbf" radius={[0, 6, 6, 0]} />
          <Bar isAnimationActive={false} name={de ? 'Letzte 3 Monate' : 'Last 3 months'} dataKey="recent" fill="#b5654f" radius={[0, 6, 6, 0]} />
        </BarChart></ResponsiveContainer></div>
    </Panel>}
    {savings.recurring.length > 0 && <Panel title={de ? 'Wiederkehrende Kosten' : 'Recurring costs'} description={de ? 'Verträge und Abos aus dem Export bzw. erkannt (Schätzung). Prüfe, was du kündigen oder neu verhandeln kannst.' : 'Contracts and subscriptions from the export or inferred (estimate).'}>
      <table className="data-table"><thead><tr><th>{de ? 'Name' : 'Name'}</th><th>{de ? 'Pro Monat' : 'Per month'}</th><th>{de ? 'Rhythmus' : 'Period'}</th><th>{de ? 'Preisänderung' : 'Price change'}</th></tr></thead>
        <tbody>{savings.recurring.map(r => <tr key={r.name}><td>{r.name}</td><td><Money value={r.monthly_cost} currency={currency} /></td><td>{r.period}</td><td>{r.price_change && Number(r.price_change) !== 0 ? <Money value={r.price_change} currency={currency} className={Number(r.price_change) > 0 ? 'negative-text' : ''} /> : '—'}</td></tr>)}</tbody></table>
    </Panel>}
  </>
}
