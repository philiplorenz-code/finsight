import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useLocale } from '../lib/i18n'
import { Money, Panel } from './ui'
import { StatusDot, type PlanReport } from '../pages/plan'

// Traffic light for the running month on the overview; hidden until the owner has plan items.
export function PlanPanel() {
  const { language } = useLocale(); const de = language === 'de'
  const query = useQuery({ queryKey: ['plan', 'overview'], queryFn: () => api<PlanReport>('/plan?history=1') })
  const items = query.data?.items ?? []
  if (!items.length) return null
  const order = { over: 0, warning: 1, ok: 2 } as const
  return <Panel title={de ? 'Soll / Ist diesen Monat' : 'Plan vs. actual this month'} action={<Link to="/plan">{de ? 'Alle Posten' : 'All items'}</Link>}>
    <ul className="plan-list">{items.slice().sort((a, b) => order[a.status] - order[b.status]).slice(0, 8).map(i => <li key={i.id}>
      <StatusDot status={i.status} de={de} /><span>{i.name}</span><span className="muted small"><Money value={i.actual} /> / <Money value={i.amount} /></span>
    </li>)}</ul>
  </Panel>
}
