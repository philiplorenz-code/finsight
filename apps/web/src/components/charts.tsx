import { useId } from 'react'
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Overview } from '../lib/types'
import { formatMoney, useLocale } from '../lib/i18n'
import { Badge, DataTable, Money, Panel } from './ui'
const colors = ['#287a68', '#91b7a5', '#d5aa64', '#bcccbf', '#7a8c96', '#c8b7a8']
export function CashflowChart({ trends, currency }: { trends?: Overview['trends']; currency: string }) {
  const { t, language } = useLocale()
  const gradientId = useId().replaceAll(':', '')
  return <Panel title={t('cashflow')} description={t('cashflowText')} action={<Badge>{currency}</Badge>}>
    <div className="chart-legend"><span><i style={{ background: '#2d8b72' }} />{t('income')}</span><span><i style={{ background: '#d4ab70' }} />{t('expenses')}</span></div>
    <div className="chart-container" role="img" aria-label={`${t('cashflow')}: ${trends?.length || 0} ${language === 'de' ? 'Datenpunkte' : 'data points'}`}>
      {trends?.length ? <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={trends.map(d => ({ ...d, income: Number(d.income), expenses: Number(d.expenses) }))} margin={{ left: -20, right: 12, top: 20, bottom: 0 }}>
          <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2d8b72" stopOpacity={0.2} /><stop offset="100%" stopColor="#2d8b72" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
          <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
          <Tooltip formatter={v => formatMoney(String(v), currency, language)} contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12 }} />
          <Area isAnimationActive={false} name={t('income')} dataKey="income" type="monotone" stroke="#2d8b72" strokeWidth={2.5} fill={`url(#${gradientId})`} />
          <Area isAnimationActive={false} name={t('expenses')} dataKey="expenses" type="monotone" stroke="#d4ab70" strokeWidth={2.5} fill="transparent" />
        </AreaChart>
      </ResponsiveContainer> : <div className="chart-empty">{t('noChart')}</div>}
    </div>
    {!!trends?.length && <details className="chart-accessible"><summary>{t('details')}</summary><DataTable headers={[t('date'), t('income'), t('expenses')]}>{trends.map(d => <tr key={d.month}><td>{d.month}</td><td><Money value={d.income} currency={currency} /></td><td><Money value={d.expenses} currency={currency} /></td></tr>)}</DataTable></details>}
  </Panel>
}
export function SpendingChart({ categories, currency }: { categories?: Overview['categories']; currency: string }) {
  const { t, language } = useLocale()
  return <Panel title={t('spending')} description={t('spendingText')}>
    <div className="donut-container" aria-hidden="true">
      {categories?.some(c => Number(c.amount) > 0) ? <ResponsiveContainer width="100%" height="100%"><PieChart>
        <Pie isAnimationActive={false} data={categories.map(c => ({ ...c, value: Number(c.amount) }))} dataKey="value" nameKey="name" innerRadius={63} outerRadius={86} stroke="var(--panel)" strokeWidth={4}>
          {categories.map((c, i) => <Cell key={c.name} fill={colors[i % colors.length]} />)}
        </Pie>
        <Tooltip formatter={v => formatMoney(String(v), currency, language)} contentStyle={{ background: 'var(--panel)', borderRadius: 12 }} />
      </PieChart></ResponsiveContainer> : <div className="chart-empty">{t('noChart')}</div>}
    </div>
    <div className="category-scroll" role="region" aria-label={language === 'de' ? 'Ausgabenkategorien' : 'Spending categories'} tabIndex={0}><ul className="category-list">{categories?.map((c, i) => <li key={c.name}><span><i aria-hidden="true" style={{ background: colors[i % colors.length] }} />{c.name}</span><Money value={c.amount} currency={currency} /></li>)}</ul></div>
  </Panel>
}
