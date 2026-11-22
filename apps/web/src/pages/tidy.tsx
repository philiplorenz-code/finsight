import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Sparkles } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, formatMoney, useLocale } from '../lib/i18n'
import { Badge, Button, Feedback, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Group = { merchant: string; count: number; total: string; last: string; sample: string; suggestion?: string | null; suggestion_source?: string | null }
type Inbox = { months: number; groups: Group[]; group_count: number; total: string; monthly: string }

export default function TidyPage() {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['tidy'], queryFn: () => api<Inbox>('/tidy/inbox?months=12') })
  const cats = useQuery({ queryKey: ['plan', 'categories'], queryFn: () => api<{ categories: string[] }>('/plan?history=1') })
  const [choice, setChoice] = useState<Record<string, string>>({})
  const [done, setDone] = useState<Record<string, number | string>>({})
  const apply = useMutation({
    mutationFn: ({ merchant, category }: { merchant: string; category: string }) => send<{ reapplied?: number }>('/category-rules', { name: `${merchant} → ${category}`.slice(0, 200), category, pattern: merchant.slice(0, 200), match_field: 'merchant', flow: 'expense' }),
    onSuccess: (r, v) => { setDone(d => ({ ...d, [v.merchant]: r?.reapplied ?? v.category })); client.invalidateQueries({ queryKey: ['transactions'] }); client.invalidateQueries({ queryKey: ['overview'] }) },
  })
  const d = query.data
  const money = (v: string) => formatMoney(v, 'EUR', language)
  return <>
    <PageHeader title={de ? 'Aufräumen' : 'Tidy up'} description={de ? 'Buchungen ohne richtige Kategorie, nach Händler gruppiert. Ein Klick legt eine Regel an, die alle bisherigen und künftigen Buchungen dieses Händlers einordnet.' : 'Bookings without a useful category, grouped by merchant. One click creates a rule for past and future bookings.'}
      action={<Button variant="outline" onClick={() => { setDone({}); query.refetch() }}>{de ? 'Neu laden' : 'Reload'}</Button>} />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch} >{d && (!d.groups.length ? <Notice>{de ? 'Alles eingeordnet – keine Buchungen ohne Kategorie in den letzten 12 Monaten.' : 'All sorted – no uncategorised bookings in the last 12 months.'}</Notice> : <>
      <Notice>{de ? `${d.group_count} Händler ohne Kategorie, zusammen ${money(d.total)} in ${d.months} Monaten (${money(d.monthly)} pro Monat).` : `${d.group_count} merchants without category, ${money(d.total)} in ${d.months} months.`}</Notice>
      <Panel>
        <datalist id="tidy-categories">{(cats.data?.categories ?? []).map(c => <option key={c} value={c} />)}</datalist>
        <ul className="tidy-list">{d.groups.map(g => { const value = choice[g.merchant] ?? g.suggestion ?? ''; const finished = done[g.merchant] !== undefined; return <li key={g.merchant} className={finished ? 'finished' : ''}>
          <div className="open-head"><strong>{g.merchant}</strong><span className="num">{money(g.total)}</span></div>
          <div className="small muted">{g.count} {de ? (g.count === 1 ? 'Buchung' : 'Buchungen') : (g.count === 1 ? 'booking' : 'bookings')} · {de ? 'zuletzt' : 'last'} {formatDate(g.last, language)}{g.sample ? ` · ${g.sample}` : ''}</div>
          {finished ? <p className="small"><Check size={14} /> {de ? 'Regel angelegt' : 'Rule created'}{typeof done[g.merchant] === 'number' ? ` · ${done[g.merchant]} ${de ? 'Buchungen aktualisiert' : 'bookings updated'}` : ''}</p> :
            <form className="tidy-form" onSubmit={e => { e.preventDefault(); if (value.trim()) apply.mutate({ merchant: g.merchant, category: value.trim() }) }}>
              <input aria-label={`${de ? 'Kategorie für' : 'Category for'} ${g.merchant}`} list="tidy-categories" maxLength={120} placeholder={de ? 'Kategorie wählen …' : 'Choose category…'} value={value} onChange={e => setChoice(c => ({ ...c, [g.merchant]: e.target.value }))} />
              {g.suggestion && <Badge>{g.suggestion_source === 'same_merchant' ? (de ? 'wie sonst bei diesem Händler' : 'as usual for this merchant') : (de ? 'Vorschlag' : 'suggested')}</Badge>}
              <Button busy={apply.isPending && apply.variables?.merchant === g.merchant} disabled={!value.trim()}><Sparkles size={14} />{de ? 'Regel anlegen' : 'Create rule'}</Button>
            </form>}
        </li> })}</ul>
        <Feedback error={apply.error} />
      </Panel>
    </>)}</QueryState>
  </>
}
