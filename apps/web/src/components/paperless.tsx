import { useQuery } from '@tanstack/react-query'
import { ExternalLink, FileText } from 'lucide-react'
import { api } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'

export type PaperlessStatus = { configured: boolean; reachable: boolean; url?: string; error?: string }
type Docs = { items: { id: number; title: string; created: string; url: string }[]; url: string }

export function usePaperless() {
  return useQuery({ queryKey: ['paperless', 'status'], queryFn: () => api<PaperlessStatus>('/paperless/status'), staleTime: 60_000 })
}

/** Documents in Paperless that match a booking's merchant. Renders nothing when Paperless is not set up. */
export function PaperlessMatches({ term }: { term?: string | null }) {
  const { language } = useLocale(); const de = language === 'de'
  const status = usePaperless()
  const q = (term ?? '').trim().slice(0, 100)
  const docs = useQuery({ queryKey: ['paperless', 'docs', q], queryFn: () => api<Docs>(`/paperless/documents?q=${encodeURIComponent(q)}`), enabled: !!status.data?.reachable && q.length >= 2 })
  if (!status.data?.reachable || q.length < 2) return null
  return <details className="source-details" open={!!docs.data?.items.length}>
    <summary>{de ? 'Dokumente in Paperless' : 'Documents in Paperless'}{docs.data ? ` (${docs.data.items.length})` : ''}</summary>
    {docs.isPending ? <p className="muted small">{de ? 'Suche …' : 'Searching…'}</p> : docs.isError ? <p className="muted small">{de ? 'Paperless gerade nicht erreichbar.' : 'Paperless not reachable.'}</p> :
      !docs.data?.items.length ? <p className="muted small">{de ? `Nichts zu „${q}“ gefunden.` : `Nothing found for "${q}".`}</p> :
      <ul className="paperless-list">{docs.data.items.map(d => <li key={d.id}><FileText size={15} /><a href={d.url} target="_blank" rel="noreferrer noopener">{d.title || `#${d.id}`}</a><small className="muted">{formatDate(d.created, language)}</small><ExternalLink size={13} /></li>)}</ul>}
  </details>
}
