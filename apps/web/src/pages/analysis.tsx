import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Series = {
  months: string[]; income: Record<string, string[]>; expenses: string[]; tax: string[]; surplus: string[]
  categories: Record<string, string[]>; other_categories: string[]; top_merchants: { merchant: string; total: string }[]
}
type Analytics = { currency: string; months_used: number; data_through: string | null; series: Series }

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
        month, income: income[i], expenses: expenses[i], tax: tax[i], surplus: surplus[i], cumulative: running,
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
