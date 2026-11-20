import { useMemo, useState } from 'react'
import type { Account } from '../lib/types'
import { useLocale } from '../lib/i18n'

/** Searchable account picker; accounts sharing a name get a short id suffix so they can be told apart. */
export function accountLabels(accounts: Pick<Account, 'id' | 'name'>[]) {
  const counts = new Map<string, number>()
  accounts.forEach(a => counts.set(a.name, (counts.get(a.name) ?? 0) + 1))
  return accounts.map(a => ({ id: a.id, label: (counts.get(a.name) ?? 0) > 1 ? `${a.name} · …${a.id.slice(-4)}` : a.name }))
}

export function AccountSelect({ accounts, value, onChange, anyLabel, label }: { accounts: Pick<Account, 'id' | 'name'>[]; value: string; onChange: (id: string) => void; anyLabel: string; label?: string }) {
  const { language } = useLocale()
  const [query, setQuery] = useState('')
  const options = useMemo(() => accountLabels(accounts), [accounts])
  const needle = query.trim().toLowerCase()
  const shown = options.filter(o => !needle || o.label.toLowerCase().includes(needle) || o.id === value)
  return <div className="account-select">
    {options.length > 8 && <input type="search" aria-label={language === 'de' ? 'Konten filtern' : 'Filter accounts'} placeholder={language === 'de' ? 'Konto suchen …' : 'Search accounts…'} value={query} onChange={e => setQuery(e.target.value)} />}
    <select aria-label={label ?? anyLabel} value={value} onChange={e => onChange(e.target.value)}>
      <option value="">{anyLabel}</option>
      {shown.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  </div>
}
