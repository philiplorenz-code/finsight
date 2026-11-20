import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { label } from '../lib/labels'
import { DataTable, Dialog, Money, QueryState } from './ui'
import { ZoomChart } from './zoom-chart'

type Profile = {
  name: string; count: number; spent: string; refunds: string; average: string; first: string; last: string
  months: { month: string; net_spent: string }[]; categories: { name: string; count: number }[]; accounts: { name: string; count: number }[]
  contract: { period: string; monthly: string; status: string; kind: string } | null
  recent: { id: string; date: string; amount: string; category?: string | null }[]
}

export function MerchantProfile({ name, onClose }: { name: string; onClose: () => void }) {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['merchant', name], queryFn: () => api<Profile>(`/merchants/profile?months=24&name=${encodeURIComponent(name)}`) })
  const p = query.data
  return <Dialog title={name} onClose={onClose}>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{p && <>
      <div className="stat-grid">
        <div className="detail-stat"><span>{de ? 'Ausgegeben (24 Monate)' : 'Spent (24 months)'}</span><Money value={p.spent} /></div>
        <div className="detail-stat"><span>{de ? 'Buchungen' : 'Bookings'}</span><strong>{p.count}</strong></div>
        <div className="detail-stat"><span>{de ? 'Ø pro Kauf' : 'Avg. per purchase'}</span><Money value={p.average} /></div>
        <div className="detail-stat"><span>{de ? 'Vertrag' : 'Contract'}</span><strong>{p.contract ? `${label('kind', p.contract.kind, language)} · ${label('period', p.contract.period, language)}` : (de ? 'nein' : 'no')}</strong></div>
      </div>
      <ZoomChart label={de ? 'Ausgaben pro Monat' : 'Spending per month'} x="month" height={200} series={[{ key: 'v', name: de ? 'pro Monat' : 'per month', color: '#d4ab70' }]} data={p.months.map(m => ({ month: m.month, v: Number(m.net_spent) }))} />
      <p className="muted small">{de ? 'Zeitraum' : 'Period'}: {formatDate(p.first, language)} – {formatDate(p.last, language)}{Number(p.refunds) > 0 && <> · {de ? 'Erstattungen' : 'Refunds'} <Money value={p.refunds} /></>}</p>
      <p className="small">{de ? 'Kategorien' : 'Categories'}: {p.categories.map(c => `${c.name} (${c.count})`).join(', ')} · {de ? 'Konten' : 'Accounts'}: {p.accounts.map(a => `${a.name} (${a.count})`).join(', ')}</p>
      <DataTable headers={[de ? 'Datum' : 'Date', de ? 'Kategorie' : 'Category', de ? 'Betrag' : 'Amount']}>{p.recent.map(r => <tr key={r.id}><td>{formatDate(r.date, language)}</td><td className="small">{r.category ?? '—'}</td><td><Money value={r.amount} /></td></tr>)}</DataTable>
    </>}</QueryState>
  </Dialog>
}
