import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { DataTable, Money, Panel } from './ui'

type Row = { id: string; name: string; balance: string; observed_date: string; share: string; mine: string; others: string }
type Order = { account_id: string; amount: string; active: boolean }

/** Money you hold for others (tax pots, family): balance, monthly inflow and the part that is not yours. */
export function TrustPanel({ accounts, currency }: { accounts: Row[]; currency: string }) {
  const { language } = useLocale(); const de = language === 'de'
  const orders = useQuery({ queryKey: ['standing-orders'], queryFn: () => api<{ transfers: Order[] }>('/standing-orders') })
  const rows = accounts.filter(a => Number(a.others) !== 0)
  if (!rows.length) return null
  const monthly = (id: string) => (orders.data?.transfers ?? []).filter(o => o.active && o.account_id === id).reduce((s, o) => s + Number(o.amount), 0)
  const total = rows.reduce((s, r) => s + Number(r.others), 0)
  return <Panel title={de ? 'Treuhand: Geld anderer' : 'Held in trust: money of others'} description={de ? 'Konten mit Anteil unter 100 %, z. B. Steuerrücklagen oder Geld für Familie. Zählt weder als dein Vermögen noch als Ausgabe.' : 'Accounts with a share below 100 %, e.g. tax reserves or money for family. Neither your net worth nor spending.'}>
    <DataTable headers={[de ? 'Konto' : 'Account', de ? 'Stand' : 'Balance', de ? 'Gehört anderen' : 'Belongs to others', de ? 'Monatlich dazu' : 'Added monthly', de ? 'Stand vom' : 'As of']}>
      {rows.map(r => <tr key={r.id}><td>{r.name}<div className="small muted">{de ? 'dein Anteil' : 'your share'} {Number(r.share).toFixed(0)} %</div></td><td><Money value={r.balance} currency={currency} /></td><td><Money value={r.others} currency={currency} /></td>
        <td>{monthly(r.id) ? <Money value={String(monthly(r.id))} currency={currency} /> : '—'}</td><td className="small muted">{formatDate(r.observed_date, language)}</td></tr>)}
      <tr><td><strong>{de ? 'Summe' : 'Total'}</strong></td><td /><td><strong><Money value={String(total)} currency={currency} /></strong></td><td colSpan={2} /></tr>
    </DataTable>
  </Panel>
}
