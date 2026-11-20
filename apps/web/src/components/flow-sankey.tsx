import { useQuery } from '@tanstack/react-query'
import { Layer, Rectangle, ResponsiveContainer, Sankey, Tooltip } from 'recharts'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { Panel } from './ui'

type Flows = { currency: string; months: number; nodes: { name: string }[]; links: { source: number; target: number; value: number }[] }
const COLORS = ['#2d8b72', '#5b8fd1', '#91b7a5', '#d4ab70', '#c8b7a8', '#7a8c96', '#e76f51', '#bcccbf', '#a98bd1', '#e9c46a']

function NodeShape(props: { x: number; y: number; width: number; height: number; index: number; payload: { name: string; value: number }; containerWidth: number; currency: string; language: string }) {
  const { x, y, width, height, index, payload, containerWidth, currency, language } = props
  const right = x + width + 6 > containerWidth - 160
  return <Layer key={`node-${index}`}>
    <Rectangle x={x} y={y} width={width} height={height} fill={COLORS[index % COLORS.length]} fillOpacity={0.9} radius={3} />
    <text x={right ? x - 6 : x + width + 6} y={y + height / 2} textAnchor={right ? 'end' : 'start'} dominantBaseline="middle" fontSize={11} fill="var(--text, currentColor)">
      {payload.name} · {formatMoney(String(Math.round(payload.value)), currency, language).replace(/,00/, '')}
    </text>
  </Layer>
}

export function FlowSankey() {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['flows'], queryFn: () => api<Flows>('/flows') })
  const d = query.data
  if (!d?.links.length) return null
  return <Panel title={de ? 'Regelmäßige Geldflüsse' : 'Regular money flows'} description={de ? `Durchschnitt pro Monat aus ${d.months} Monaten: woher dein Geld kommt und wohin es geht.` : `Monthly average over ${d.months} months: where your money comes from and where it goes.`}>
    <div className="sankey-container" role="img" aria-label={de ? 'Sankey-Diagramm der Geldflüsse' : 'Sankey diagram of money flows'}>
      <ResponsiveContainer width="100%" height={380}>
        <Sankey data={d} nodePadding={14} nodeWidth={10} margin={{ left: 8, right: 8, top: 10, bottom: 10 }} link={{ stroke: '#91b7a5', strokeOpacity: 0.35 }}
          node={(p: object) => <NodeShape {...(p as Parameters<typeof NodeShape>[0])} containerWidth={900} currency={d.currency} language={language} />}>
          <Tooltip formatter={v => formatMoney(String(v), d.currency, language)} />
        </Sankey>
      </ResponsiveContainer>
    </div>
  </Panel>
}
