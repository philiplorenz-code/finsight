import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatMoney, useLocale } from '../lib/i18n'
import { DataTable, Field, Notice, Panel } from './ui'

type Wish = { id: string; name: string; price: string; priority: number; status: string; follow_up_monthly_cost: string }
type Data = {
  baseline: { expected_surplus: string; conservative_surplus: string; usable_cash: string; monthly_consumption: string; monthly_income: string; currency: string
    income_sources: Record<string, { monthly_average: string; monthly_lower_quartile: string }> }
  wishes: Wish[]
}

/** What-if: change salary, side business, rent and savings rate and see surplus, cash and wishes at once. All in the browser. */
export function Simulator() {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['wishlist'], queryFn: () => api<Data>('/wishlist') })
  const [salary, setSalary] = useState(0)
  const [business, setBusiness] = useState(100)
  const [rent, setRent] = useState(0)
  const [saving, setSaving] = useState(0)
  const b = query.data?.baseline
  const result = useMemo(() => {
    if (!b) return null
    const biz = Number(b.income_sources?.business?.monthly_average ?? 0)
    const bizWeak = Number(b.income_sources?.business?.monthly_lower_quartile ?? 0)
    const bizDelta = biz * (business / 100 - 1)
    const delta = salary + bizDelta - rent - saving
    const expected = Number(b.expected_surplus) + delta
    const cautious = Number(b.conservative_surplus) + salary + bizWeak * (business / 100 - 1) - rent - saving
    let free = Number(b.usable_cash)
    const wishes = (query.data?.wishes ?? []).filter(w => w.status === 'open').sort((x, y) => x.priority - y.priority).map(w => {
      const price = Number(w.price)
      const monthsExp = free >= price ? 0 : expected > 0 ? Math.ceil((price - free) / expected) : null
      const monthsCau = free >= price ? 0 : cautious > 0 ? Math.ceil((price - free) / cautious) : null
      free = Math.max(0, free - price)
      return { ...w, monthsExp, monthsCau }
    })
    return { expected, cautious, cash12: Number(b.usable_cash) + expected * 12, cash12c: Number(b.usable_cash) + cautious * 12, wishes, delta }
  }, [b, query.data, salary, business, rent, saving])
  if (!b || !result) return null
  const money = (v: number) => formatMoney(String(Math.round(v)), b.currency, language).replace(/,00/, '')
  const verdict = (m: number | null) => m === 0 ? (de ? 'sofort' : 'now') : m == null ? (de ? 'nicht absehbar' : 'not foreseeable') : `${m} ${de ? 'Mon.' : 'mo.'}`
  const slider = (labelText: string, value: number, set: (v: number) => void, min: number, max: number, step: number, unit: string) =>
    <Field label={`${labelText}: ${value > 0 && unit !== '%' ? '+' : ''}${value}${unit}`}><input type="range" min={min} max={max} step={step} value={value} onChange={e => set(Number(e.target.value))} /></Field>
  return <Panel title={de ? 'Was wäre wenn?' : 'What if?'} description={de ? 'Schieb die Regler – Überschuss, Geld in 12 Monaten und deine Wünsche rechnen sich sofort neu.' : 'Move the sliders – surplus, cash in 12 months and your wishes update instantly.'}>
    <div className="form-grid">
      {slider(de ? 'Gehalt netto pro Monat' : 'Net salary per month', salary, setSalary, -1500, 1500, 50, ' €')}
      {slider(de ? 'Nebengewerbe' : 'Side business', business, setBusiness, 0, 200, 10, '%')}
      {slider(de ? 'Miete' : 'Rent', rent, setRent, -800, 800, 25, ' €')}
      {slider(de ? 'Zusätzliche Sparrate' : 'Extra savings', saving, setSaving, 0, 1500, 25, ' €')}
    </div>
    <div className="stat-grid">
      <div className="detail-stat"><span>{de ? 'Überschuss erwartet' : 'Expected surplus'}</span><strong>{money(result.expected)}</strong><small className="muted">{de ? 'vorsichtig' : 'cautious'} {money(result.cautious)}</small></div>
      <div className="detail-stat"><span>{de ? 'Freies Geld in 12 Monaten' : 'Free cash in 12 months'}</span><strong>{money(result.cash12)}</strong><small className="muted">{de ? 'vorsichtig' : 'cautious'} {money(result.cash12c)}</small></div>
      <div className="detail-stat"><span>{de ? 'Veränderung pro Monat' : 'Change per month'}</span><strong>{money(result.delta)}</strong></div>
    </div>
    {!!result.wishes.length && <DataTable headers={[de ? 'Wunsch' : 'Wish', de ? 'Preis' : 'Price', de ? 'Erwartet' : 'Expected', de ? 'Vorsichtig' : 'Cautious']}>
      {result.wishes.map(w => <tr key={w.id}><td>{w.name}</td><td>{money(Number(w.price))}</td><td>{verdict(w.monthsExp)}</td><td>{verdict(w.monthsCau)}</td></tr>)}
    </DataTable>}
    <Notice>{de ? 'Vereinfachte Rechnung: Änderungen wirken ab sofort und dauerhaft, Steuern auf Mehreinnahmen sind nicht berücksichtigt. Wünsche werden nach Priorität nacheinander bezahlt.' : 'Simplified: changes apply immediately and permanently; tax on extra income is not modelled. Wishes are paid in priority order.'}</Notice>
  </Panel>
}
