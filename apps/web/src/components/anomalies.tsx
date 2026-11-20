import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'
import { Panel } from './ui'

type Anomaly = { key: string; kind: 'double_debit' | 'unusually_high' | 'new_recurring' | 'price_increase'; severity: 'high' | 'medium' | 'low'; date: string; merchant?: string; amount: string; typical?: string; change?: string; period?: string }

const TEXT: Record<Anomaly['kind'], [string, string]> = {
  double_debit: ['Mögliche Doppelabbuchung', 'Possible double debit'], unusually_high: ['Ungewöhnlich hoher Betrag', 'Unusually high amount'],
  new_recurring: ['Neue wiederkehrende Zahlung', 'New recurring payment'], price_increase: ['Preiserhöhung', 'Price increase'],
}

export function AnomalyPanel({ days = 60, limit = 8, compact = false }: { days?: number; limit?: number; compact?: boolean }) {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['anomalies', days], queryFn: () => api<{ items: Anomaly[] }>(`/anomalies?days=${days}`) })
  const items = (query.data?.items ?? []).filter(a => !compact || a.severity === 'high' || a.kind !== 'unusually_high')
  if (!items.length) return compact ? null : <Panel title={de ? 'Auffälligkeiten' : 'Anomalies'}><p className="muted">{de ? `Keine Auffälligkeiten in den letzten ${days} Tagen.` : `Nothing unusual in the last ${days} days.`}</p></Panel>
  const money = (v?: string) => formatMoney(v ?? '0', 'EUR', language)
  const detail = (a: Anomaly) => a.kind === 'unusually_high' ? (de ? `sonst typisch ${money(a.typical)}` : `usually ${money(a.typical)}`)
    : a.kind === 'price_increase' ? (de ? `+${money(a.change)} je Zahlung` : `+${money(a.change)} per charge`)
    : a.kind === 'double_debit' ? (de ? 'gleicher Betrag innerhalb von 3 Tagen' : 'same amount within 3 days') : (de ? 'seit Kurzem' : 'recently started')
  return <Panel title={de ? 'Auffälligkeiten' : 'Anomalies'} description={de ? `Letzte ${days} Tage – Hinweise zum Prüfen, keine Fehlerbestätigung.` : `Last ${days} days – hints to check, not confirmed errors.`}>
    <ul className="upcoming-list">{items.slice(0, limit).map(a => <li key={a.key}>
      <span className={`upcoming-icon anomaly-${a.severity}`}><AlertTriangle size={15} /></span>
      <span><strong>{TEXT[a.kind][de ? 0 : 1]}: {a.merchant}</strong><small className="muted">{formatDate(a.date, language)} · {detail(a)}</small></span>
      <strong>{money(a.amount)}</strong>
    </li>)}</ul>
  </Panel>
}
