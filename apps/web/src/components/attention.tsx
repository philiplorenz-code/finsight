import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlarmClock, CircleAlert, HandCoins, Target } from 'lucide-react'
import { api } from '../lib/api'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'
import { Panel } from './ui'

type Item = { kind: 'deadline' | 'overdue' | 'settle' | 'plan_over' | 'plan_warning'; severity: 'high' | 'medium' | 'low'; title: string; person?: string
  amount?: string; target?: string; projected?: string | null; remaining?: string; date?: string; days_left?: number; direction?: string; link: string }
const ICON = { deadline: AlarmClock, overdue: CircleAlert, settle: HandCoins, plan_over: Target, plan_warning: Target }

/** Everything that needs a decision soon, in one place on the overview. Hidden when nothing is due. */
export function AttentionPanel() {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['attention'], queryFn: () => api<{ items: Item[] }>('/attention') })
  const items = query.data?.items ?? []
  if (!items.length) return null
  const money = (v?: string) => formatMoney(v ?? '0', 'EUR', language)
  const text = (i: Item) => ({
    deadline: de ? `Kündigen bis ${formatDate(i.date, language)} – noch ${i.days_left} Tage` : `Cancel by ${formatDate(i.date, language)} – ${i.days_left} days left`,
    overdue: de ? `${i.direction === 'receivable' ? 'Bekommst du' : 'Schuldest du'} ${money(i.amount)} · ${i.person} · fällig seit ${formatDate(i.date, language)}` : `${money(i.amount)} · ${i.person} · due since ${formatDate(i.date, language)}`,
    settle: de ? `Zahlung gefunden: ${money(i.amount)} von ${i.person} – abhaken?` : `Payment found: ${money(i.amount)} from ${i.person} – settle?`,
    plan_over: de ? `${money(i.amount)} von ${money(i.target)} ausgegeben` : `${money(i.amount)} of ${money(i.target)} spent`,
    plan_warning: de ? `${money(i.amount)} von ${money(i.target)} – noch ${money(i.remaining)} übrig${i.projected ? `, Hochrechnung ${money(i.projected)}` : ''}` : `${money(i.amount)} of ${money(i.target)} – ${money(i.remaining)} left${i.projected ? `, projected ${money(i.projected)}` : ''}`,
  })[i.kind]
  return <Panel title={de ? 'Jetzt wichtig' : 'Needs attention'} className="attention-panel">
    <ul className="upcoming-list">{items.slice(0, 6).map((i, n) => { const Icon = ICON[i.kind]; return <li key={n}>
      <span className={`upcoming-icon anomaly-${i.severity === 'low' ? 'medium' : i.severity}`}><Icon size={15} /></span>
      <span><strong>{i.title}</strong><small className="muted">{text(i)}</small></span>
      <Link to={i.link} className="small">{de ? 'Öffnen' : 'Open'}</Link>
    </li> })}</ul>
  </Panel>
}
