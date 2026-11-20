import { useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatMoney, useLocale } from '../lib/i18n'
import { Button } from './ui'

export type Series = { key: string; name: string; color: string; fill?: boolean }
type Point = Record<string, string | number | null>

/**
 * Time series with Grafana-style zoom: press, drag across a time range and release to zoom in;
 * double-click or "Zoom zurücksetzen" returns to the full range. Points must be sorted by `x`.
 */
export function ZoomChart({ data, series, x = 'x', currency = 'EUR', height = 260, label, step }: {
  data: Point[]; series: Series[]; x?: string; currency?: string; height?: number; label: string; step?: boolean
}) {
  const { language } = useLocale(); const de = language === 'de'
  const [range, setRange] = useState<[number, number] | null>(null)
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null)
  const visible = useMemo(() => (range ? data.slice(range[0], range[1] + 1) : data), [data, range])
  const offset = range ? range[0] : 0
  // recharts reports the hovered point as tooltip index (string) and label; accept either.
  const indexOf = (state: unknown) => {
    const e = (state ?? {}) as { activeTooltipIndex?: string | number | null; activeLabel?: unknown }
    if (e.activeTooltipIndex != null && e.activeTooltipIndex !== '' && !Number.isNaN(Number(e.activeTooltipIndex))) return Number(e.activeTooltipIndex) + offset
    const i = visible.findIndex(p => p[x] === e.activeLabel)
    return i < 0 ? null : i + offset
  }
  const finish = (state: unknown) => {
    const end = indexOf(state) ?? drag?.to
    if (drag && end != null && Math.abs(end - drag.from) >= 1) setRange([Math.min(drag.from, end), Math.max(drag.from, end)])
    setDrag(null)
  }
  const tick = { fill: 'var(--muted)', fontSize: 11 }
  return <div className="zoom-chart">
    <div className="zoom-chart-bar">
      <span className="muted small">{range ? `${String(data[range[0]][x])} – ${String(data[range[1]][x])}` : (de ? 'Zum Zoomen einen Zeitraum mit der Maus aufziehen' : 'Drag across a time range to zoom')}</span>
      {range && <Button type="button" variant="outline" onClick={() => setRange(null)}>{de ? 'Zoom zurücksetzen' : 'Reset zoom'}</Button>}
    </div>
    <div style={{ height, userSelect: 'none' }} role="img" aria-label={`${label}: ${visible.length} ${de ? 'Datenpunkte' : 'data points'}`} onDoubleClick={() => setRange(null)}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={visible} margin={{ left: 0, right: 12, top: 12, bottom: 0 }}
          onMouseDown={e => { const i = indexOf(e); if (i != null) setDrag({ from: i, to: i }) }}
          onMouseMove={e => { if (!drag) return; const i = indexOf(e); if (i != null && i !== drag.to) setDrag({ ...drag, to: i }) }}
          onMouseUp={finish} onMouseLeave={() => setDrag(null)}>
          <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
          <XAxis dataKey={x} axisLine={false} tickLine={false} tick={tick} minTickGap={24} />
          <YAxis axisLine={false} tickLine={false} tick={tick} width={64} tickFormatter={v => formatMoney(String(v), currency, language).replace(/,\d\d/, '')} />
          <Tooltip formatter={v => formatMoney(String(v), currency, language)} contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12 }} />
          {series.map(s => <Area key={s.key} isAnimationActive={false} name={s.name} dataKey={s.key} type={step ? 'stepAfter' : 'monotone'} stroke={s.color} strokeWidth={2.2} fill={s.fill === false ? 'transparent' : s.color} fillOpacity={s.fill === false ? 0 : 0.12} connectNulls />)}
          {drag && drag.from !== drag.to && <ReferenceArea x1={String(data[Math.min(drag.from, drag.to)][x])} x2={String(data[Math.max(drag.from, drag.to)][x])} strokeOpacity={0.3} fill="var(--accent, #2d8b72)" fillOpacity={0.15} />}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  </div>
}
