import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { normalizeMcpConnections, safeMcpRedirect, type McpConnections } from '../lib/mcp'
import { Badge, Button, Feedback, Field, Notice, Panel, QueryState } from './ui'

export function McpDisclosure() {
  const { language } = useLocale()
  return <Notice warning>{language === 'de' ? 'Der externe Client und seine KI-/Cloud-Anbieter erhalten die abgefragten Finanzdaten. Es gelten deren Datenschutz- und Aufbewahrungsregeln. Das FinSight-KI-Budget deckt keine LLM-Kosten des Clients ab. Alle Tools sind nur lesend; keine Überweisungen oder Änderungen. Standardmäßig keine IBAN oder Roh-Verwendungszwecke. Der optionale Scope finance:transactions erlaubt detailliertere Buchungen einschließlich Händlern und Beträgen.' : 'The external client and its AI/cloud providers receive the queried financial data. Their privacy and retention policies apply. The FinSight AI budget does not cover client LLM costs. All tools are read-only; no transfers or changes. No IBANs or raw payment references by default. The optional finance:transactions scope permits more detailed transactions including merchants and amounts.'}</Notice>
}

export function McpSettings() {
  const { language } = useLocale()
  const client = useQueryClient()
  const [copy, setCopy] = useState<'idle' | 'ok' | 'error'>('idle')
  const query = useQuery({ queryKey: ['mcp-connections'], queryFn: async () => normalizeMcpConnections(await api<McpConnections | McpConnections['connections']>('/mcp/connections')), retry: false })
  const revoke = useMutation({ mutationFn: (id: string) => send(`/mcp/connections/${encodeURIComponent(id)}`, undefined, 'DELETE'), onSuccess: () => client.invalidateQueries({ queryKey: ['mcp-connections'] }) })
  const endpoint = safeMcpRedirect(query.data?.endpoint)
  return <div id="mcp" className="mcp-section"><Panel title={language === 'de' ? 'MCP · ChatGPT & externe Clients' : 'MCP · ChatGPT & external clients'}>
    <div className="form-stack">
      <McpDisclosure />
      <Notice>{language === 'de' ? 'Standardmäßig ausgeschaltet (MCP_ENABLED=false). Nur der Betreiber kann MCP auf dem Server aktivieren; diese Seite kann das nicht überschreiben.' : 'Disabled by default (MCP_ENABLED=false). Only the operator can enable MCP on the server; this page cannot override it.'}</Notice>
      <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>
        {query.data && <>
          <div className="badge-row"><Badge>{query.data.enabled === null ? (language === 'de' ? 'Serverstatus nicht verfügbar' : 'Server status unavailable') : query.data.enabled ? (language === 'de' ? 'Server aktiviert' : 'Server enabled') : (language === 'de' ? 'Server deaktiviert' : 'Server disabled')}</Badge><Badge>{language === 'de' ? 'Nur lesend' : 'Read-only'}</Badge>{query.data.scopes.map(scope => <Badge key={scope}>{scope}</Badge>)}</div>
          {!endpoint && <Notice>{language === 'de' ? 'Der Server liefert keinen gültigen MCP-Endpunkt. Öffentliche HTTPS-URL beim Betreiber erfragen.' : 'The server did not provide a valid MCP endpoint. Ask the operator for the public HTTPS URL.'}</Notice>}
          <Field label={language === 'de' ? 'MCP-Endpunkt' : 'MCP endpoint'}><input readOnly value={endpoint || '—'} /></Field>
          <div><Button type="button" variant="outline" disabled={!endpoint} onClick={async () => { try { await navigator.clipboard.writeText(endpoint!); setCopy('ok') } catch { setCopy('error') } }}>{language === 'de' ? 'Endpunkt kopieren' : 'Copy endpoint'}</Button></div>
          {copy !== 'idle' && <p role="status">{copy === 'ok' ? (language === 'de' ? 'Kopiert.' : 'Copied.') : (language === 'de' ? 'Kopieren nicht verfügbar. URL im Feld manuell kopieren.' : 'Clipboard unavailable. Copy the URL from the field manually.')}</p>}
          <h3>{language === 'de' ? 'Verbindungen' : 'Connections'}</h3>
          {!query.data.connections.length && <p className="muted">{language === 'de' ? 'Keine freigegebenen Verbindungen.' : 'No authorized connections.'}</p>}
          {query.data.connections.map(connection => <article className="mcp-connection form-stack" key={connection.id}>
            <strong>{connection.client_name}</strong>
            <div className="badge-row">{connection.scopes.map(scope => <Badge key={scope}>{scope}</Badge>)}</div>
            <p className="muted small">{language === 'de' ? 'Freigegeben:' : 'Authorized:'} {formatDate(connection.created_at, language)} · {language === 'de' ? 'Zuletzt verwendet:' : 'Last used:'} {formatDate(connection.last_used_at || undefined, language)}</p>
            <div><Button type="button" variant="outline" busy={revoke.isPending && revoke.variables === connection.id} disabled={revoke.isPending} onClick={() => revoke.mutate(connection.id)} aria-label={`${language === 'de' ? 'Verbindung widerrufen' : 'Revoke connection'}: ${connection.client_name}`}>{language === 'de' ? 'Verbindung widerrufen' : 'Revoke connection'}</Button></div>
          </article>)}
        </>}
      </QueryState>
      <Feedback error={revoke.error} success={revoke.isSuccess} />
      <h3>{language === 'de' ? 'In ChatGPT einrichten' : 'Set up in ChatGPT'}</h3>
      <p>{language === 'de' ? 'Einstellungen → Apps → Entwicklermodus: Remote-MCP-App hinzufügen, den MCP-Endpunkt eintragen und OAuth wählen. Die Bezeichnungen können je nach Client-Version abweichen. Der Server muss unter einer öffentlich erreichbaren HTTPS-URL verfügbar sein; localhost reicht für einen Cloud-Client nicht aus. Anschließend in FinSight anmelden und die angefragten Scopes ausdrücklich freigeben.' : 'Settings → Apps → Developer mode: add a remote MCP app, enter the MCP endpoint and choose OAuth. Labels may differ by client version. The server needs a publicly reachable HTTPS URL; localhost is not sufficient for a cloud client. Then sign in to FinSight and explicitly authorize the requested scopes.'}</p>
      <p className="muted small">{language === 'de' ? 'Verfügbarkeit hängt von Anbieter, Tarif, Workspace und Client-Version ab. Keine Live-Verifikation mit ChatGPT durchgeführt. Widerruf beendet künftigen Zugriff, löscht aber keine bereits beim Anbieter gespeicherten Daten.' : 'Availability depends on provider, plan, workspace and client version. Not live-verified with ChatGPT. Revocation stops future access but does not delete data already retained by the provider.'}</p>
    </div>
  </Panel></div>
}

export function McpSettingsLink() {
  const { language } = useLocale()
  return <Link className="button button-outline" to="/settings/mcp">{language === 'de' ? 'MCP-Verbindungen verwalten' : 'Manage MCP connections'}</Link>
}
