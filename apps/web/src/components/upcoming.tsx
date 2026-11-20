import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowRightLeft, CalendarClock } from 'lucide-react'
import { api } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { DataTable, Money, Panel } from './ui'

export type Upcoming = { date: string; kind: 'contract' | 'transfer' | 'income'; name: string; amount: string; currency: string; account?: string | null; detail?: string }

const ICON = { contract: CalendarClock, transfer: ArrowRightLeft, income: ArrowDownLeft }
const KIND: Record<string, [string, string]> = { subscription: ['Abo', 'Subscription'], insurance: ['Versicherung', 'Insurance'], utility: ['Versorger', 'Utility'], housing: ['Wohnen', 'Housing'], loan: ['Kredit', 'Loan'], savings: ['Sparplan', 'Savings plan'], other: ['Vertrag', 'Contract'] }

export function UpcomingList({ days = 30, compact = false }: { days?: number; compact?: boolean }) {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['upcoming', days], queryFn: () => api<{ items: Upcoming[] }>(`/upcoming?days=${days}`) })
  const items = query.data?.items ?? []
  const kindText = (u: Upcoming) => u.kind === 'income' ? (de ? 'Erwartetes Gehalt' : 'Expected pay') : u.kind === 'transfer' ? (de ? 'Dauerauftrag in Topf' : 'Standing order') : (KIND[u.detail ?? 'other'] ?? KIND.other)[de ? 0 : 1]
  if (compact) {
    if (!items.length) return null
    return <Panel title={de ? 'Demnächst fällig' : 'Coming up'} description={de ? `Nächste ${days} Tage – erwartet, nicht von der Bank bestätigt.` : `Next ${days} days – expected, not bank-confirmed.`} action={<Link to="/plan">{de ? 'Alle' : 'All'}</Link>}>
      <ul className="upcoming-list">{items.slice(0, 7).map((u, i) => { const Icon = ICON[u.kind]; return <li key={i}>
        <span className={`upcoming-icon ${u.kind}`}><Icon size={15} /></span>
        <span><strong>{u.name}</strong><small className="muted">{formatDate(u.date, language)} · {kindText(u)}</small></span>
        <Money value={u.amount} currency={u.currency} className={Number(u.amount) < 0 ? '' : 'positive'} />
      </li> })}</ul>
    </Panel>
  }
  return <Panel title={de ? 'Demnächst fällig' : 'Coming up'} description={de ? `Erwartete Abbuchungen, Daueraufträge und Gehalt der nächsten ${days} Tage, abgeleitet aus deinen Buchungen.` : `Expected debits, standing orders and pay for the next ${days} days, derived from your bookings.`}>
    {!items.length ? <p className="muted">{de ? 'Nichts erkannt.' : 'Nothing detected.'}</p> :
      <DataTable headers={[de ? 'Datum' : 'Date', de ? 'Was' : 'What', de ? 'Art' : 'Type', de ? 'Konto' : 'Account', de ? 'Betrag' : 'Amount']}>
        {items.map((u, i) => <tr key={i}><td className="nowrap">{formatDate(u.date, language)}</td><td>{u.name}</td><td className="small">{kindText(u)}</td><td className="small muted">{u.account ?? '—'}</td><td className="nowrap"><Money value={u.amount} currency={u.currency} /></td></tr>)}
        <tr><td colSpan={4}><strong>{de ? 'Saldo der erwarteten Buchungen' : 'Net of expected bookings'}</strong></td><td><Money value={String(items.filter(u => u.kind !== 'transfer').reduce((s, u) => s + Number(u.amount), 0))} /></td></tr>
      </DataTable>}
  </Panel>
}
