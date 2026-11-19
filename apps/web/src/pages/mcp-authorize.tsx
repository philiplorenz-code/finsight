import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { McpDisclosure, McpSettingsLink } from '../components/mcp'
import { Badge, Button, Feedback, Notice, PageHeader, Panel, QueryState } from '../components/ui'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { safeMcpRedirect, type McpAuthorization } from '../lib/mcp'

export default function McpAuthorizePage() {
  const { language } = useLocale()
  const [params] = useSearchParams()
  const id = params.get('request_id') || ''
  const validId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
  const [confirmed, setConfirmed] = useState(false)
  const [transactions, setTransactions] = useState(false)
  useEffect(() => { setConfirmed(false); setTransactions(false) }, [id])
  const query = useQuery({ queryKey: ['mcp-authorization', id], queryFn: () => api<McpAuthorization>(`/mcp/authorization-requests/${id}`), enabled: validId, retry: false, staleTime: 0 })
  const decision = useMutation({ mutationFn: async (approved: boolean) => {
    const scopes = query.data?.scopes.filter(scope => scope !== 'finance:transactions' || transactions) || []
    const result = await send<{ redirect_url: string }>(`/mcp/authorization-requests/${id}/decision`, { decision: approved ? 'allow' : 'deny', scopes: approved ? scopes : [] })
    const redirect = safeMcpRedirect(result.redirect_url)
    if (!redirect) throw new Error('Unsafe OAuth redirect')
    window.location.assign(redirect)
  } })
  const expired = !!query.data && (!Number.isFinite(Date.parse(query.data.expires_at)) || Date.parse(query.data.expires_at) <= Date.now())
  const knownScopes = !!query.data?.scopes.length && query.data.scopes.every(scope => ['finance:read', 'finance:transactions'].includes(scope))
  const callback = safeMcpRedirect(query.data?.redirect_uri)
  const callbackOrigin = callback ? new URL(callback).origin : '—'
  return <><PageHeader title={language === 'de' ? 'MCP-Zugriff freigeben' : 'Authorize MCP access'} description={language === 'de' ? 'Prüfe Client und Berechtigungen, bevor du Finanzdaten freigibst.' : 'Review the client and permissions before sharing financial data.'} />
    <Panel>
      {!validId ? <Notice warning>{language === 'de' ? 'Ungültige oder fehlende Anfrage-ID. Starte die Verbindung erneut im externen Client.' : 'Invalid or missing request ID. Restart the connection in the external client.'}</Notice> : <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>
        {query.data && <div className="form-stack mcp-consent">
          <h2>{query.data.client_name}</h2>
          <Notice warning>{language === 'de' ? 'Der Client-Name ist selbst angegeben und nicht von FinSight verifiziert. Auch ein Name wie „ChatGPT“ ist kein Identitätsnachweis. Prüfe die registrierte Callback-Origin unten unabhängig anhand der Angaben des erwarteten Anbieters. Erlaube den Zugriff nur, wenn diese Origin zum beabsichtigten Client gehört.' : 'The client name is self-asserted and not verified by FinSight. Even a name such as “ChatGPT” is not proof of identity. Independently check the registered callback origin below against the expected provider’s information. Only allow access if this origin belongs to your intended client.'}</Notice>
          <p className="muted small">Client ID: {query.data.client_id}</p>
          <dl className="mcp-destinations">
            <dt>{language === 'de' ? 'Registrierte Callback-Origin' : 'Registered callback origin'}</dt>
            <dd data-testid="mcp-callback-origin">{callbackOrigin}</dd>
            <dt>{language === 'de' ? 'Registrierte Callback-URI' : 'Registered callback URI'}</dt>
            <dd data-testid="mcp-callback-uri">{query.data.redirect_uri}</dd>
            <dt>{language === 'de' ? 'FinSight-Ressource' : 'FinSight resource'}</dt>
            <dd data-testid="mcp-resource">{query.data.resource}</dd>
          </dl>
          {!callback && <Notice warning>{language === 'de' ? 'Die registrierte Callback-URI fehlt oder ist ungültig. Freigabe ist gesperrt; starte die Verbindung erneut im beabsichtigten Client.' : 'The registered callback URI is missing or invalid. Authorization is blocked; restart the connection in your intended client.'}</Notice>}
          <div className="badge-row"><Badge>{language === 'de' ? 'Nur lesend' : 'Read-only'}</Badge>{query.data.scopes.map(scope => <Badge key={scope}>{scope}</Badge>)}</div>
          <p>{language === 'de' ? 'Gültig bis:' : 'Expires:'} {formatDate(query.data.expires_at, language)}</p>
          <McpDisclosure />
          {query.data.scopes.includes('finance:transactions') && <label className="checkbox"><input type="checkbox" checked={transactions} disabled={decision.isPending || decision.isSuccess || expired} onChange={event => { setTransactions(event.target.checked); setConfirmed(false) }} />{language === 'de' ? 'Optional: detaillierte Buchungen mit Händlern und Beträgen freigeben (finance:transactions).' : 'Optional: share detailed transactions with merchants and amounts (finance:transactions).'}</label>}
          {expired && <Notice warning>{language === 'de' ? 'Die Anfrage ist abgelaufen. Starte die Verbindung erneut im Client.' : 'This request has expired. Restart the connection in the client.'}</Notice>}
          {!knownScopes && <Notice warning>{language === 'de' ? 'Unbekannte Berechtigungen. Freigabe ist aus Sicherheitsgründen gesperrt.' : 'Unknown permissions. Authorization is blocked for safety.'}</Notice>}
          <label className="checkbox"><input type="checkbox" checked={confirmed} disabled={decision.isPending || decision.isSuccess || expired || !knownScopes || !callback} onChange={event => setConfirmed(event.target.checked)} />{language === 'de' ? `Ich stimme der Übermittlung der abgefragten Finanzdaten an diesen externen Client und seine Anbieter zu. Ich habe geprüft, dass die registrierte Callback-Origin ${callbackOrigin} zum beabsichtigten Client gehört.` : `I consent to sending queried financial data to this external client and its providers. I have checked that the registered callback origin ${callbackOrigin} belongs to my intended client.`}</label>
          <div className="form-actions"><Button type="button" variant="outline" disabled={decision.isPending || decision.isSuccess || expired} onClick={() => decision.mutate(false)}>{language === 'de' ? 'Ablehnen' : 'Deny'}</Button><Button type="button" busy={decision.isPending} disabled={!confirmed || !callback || expired || !knownScopes || (!transactions && !query.data.scopes.includes('finance:read')) || decision.isSuccess} onClick={() => decision.mutate(true)}>{language === 'de' ? 'Zugriff ausdrücklich erlauben' : 'Explicitly allow access'}</Button></div>
          <Feedback error={decision.error} />
          {decision.isSuccess && <p role="status">{language === 'de' ? 'Entscheidung gespeichert. Weiterleitung zum Client …' : 'Decision saved. Returning to the client …'}</p>}
        </div>}
      </QueryState>}
      <McpSettingsLink />
    </Panel>
  </>
}
