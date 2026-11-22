import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Smartphone, Trash2 } from 'lucide-react'
import { api, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { Button, DataTable, Feedback, Field, Notice, Panel } from './ui'

type Key = { id: string; name: string; hint: string; created_at: string; last_used_at?: string | null }
type Created = Key & { key: string; upload_url: string }

/** iPhone: share the Finanzguru export from the share sheet to an iOS Shortcut that posts it here. */
export function PhoneImport() {
  const { language } = useLocale(); const de = language === 'de'
  const client = useQueryClient()
  const keys = useQuery({ queryKey: ['device-keys'], queryFn: () => api<Key[]>('/device-keys') })
  const [name, setName] = useState('iPhone')
  const [created, setCreated] = useState<Created | null>(null)
  const [copied, setCopied] = useState('')
  const create = useMutation({ mutationFn: () => send<Created>('/device-keys', { name }), onSuccess: c => { setCreated(c); client.invalidateQueries({ queryKey: ['device-keys'] }) } })
  const revoke = useMutation({ mutationFn: (id: string) => send(`/device-keys/${encodeURIComponent(id)}`, undefined, 'DELETE'), onSuccess: () => client.invalidateQueries({ queryKey: ['device-keys'] }) })
  const copy = async (text: string, what: string) => { try { await navigator.clipboard.writeText(text); setCopied(what) } catch { setCopied('') } }
  const url = `${location.origin}/api/device/import`  // the address the phone uses, i.e. this page's origin
  return <Panel title={de ? 'Import vom iPhone' : 'Import from iPhone'} action={<Smartphone size={19} />}
    description={de ? 'Excel-Export in Finanzguru oder der Dateien-App teilen → „An FinSight senden“ → fertig. Der Schlüssel darf nur Importe starten, nichts lesen.' : 'Share the export from Finanzguru or Files → “Send to FinSight” → done. The key can only start imports, not read anything.'}>
    <div className="form-grid">
      <Field label={de ? 'Gerätename' : 'Device name'}><input maxLength={80} value={name} onChange={e => setName(e.target.value)} /></Field>
      <div><Button busy={create.isPending} onClick={() => create.mutate()}>{de ? 'Upload-Schlüssel erzeugen' : 'Create upload key'}</Button></div>
    </div>
    {created && <Notice warning>
      <strong>{de ? 'Nur jetzt sichtbar – im Kurzbefehl eintragen:' : 'Shown only now – put it into the Shortcut:'}</strong>
      <div className="key-box"><code>{created.key}</code><Button type="button" variant="outline" onClick={() => copy(created.key, 'key')}><Copy size={14} />{copied === 'key' ? (de ? 'Kopiert' : 'Copied') : (de ? 'Kopieren' : 'Copy')}</Button></div>
    </Notice>}
    <ol className="setup-steps">
      <li>{de ? 'Auf dem iPhone die App „Kurzbefehle“ öffnen → „+“ → oben auf den Namen tippen: „An FinSight senden“.' : 'Open “Shortcuts” on iPhone → “+” → name it “Send to FinSight”.'}</li>
      <li>{de ? 'Info (i) → „Im Share-Sheet anzeigen“ einschalten, Eingabe: „Dateien“.' : 'Info (i) → enable “Show in Share Sheet”, input: “Files”.'}</li>
      <li>{de ? 'Aktion „Inhalte von URL abrufen“ hinzufügen. URL:' : 'Add action “Get Contents of URL”. URL:'} <span className="key-box"><code>{url}</code><Button type="button" variant="outline" onClick={() => copy(url, 'url')}><Copy size={14} />{copied === 'url' ? (de ? 'Kopiert' : 'Copied') : (de ? 'Kopieren' : 'Copy')}</Button></span></li>
      <li>{de ? 'Methode „POST“. Header: Schlüssel „Authorization“, Wert „Bearer “ + dein Upload-Schlüssel.' : 'Method “POST”. Header: key “Authorization”, value “Bearer ” + your upload key.'}</li>
      <li>{de ? 'Anfragetext „Formular“ → Feld hinzufügen → „Datei“, Name „file“, Wert: „Kurzbefehleingabe“.' : 'Request body “Form” → add field → “File”, name “file”, value “Shortcut Input”.'}</li>
      <li>{de ? 'Optional: Aktion „Mitteilung anzeigen“ mit „Inhalte von URL“ – dann siehst du „Import gestartet“.' : 'Optional: “Show Notification” with “Contents of URL” to see “Import started”.'}</li>
      <li>{de ? 'Fertig: In Finanzguru exportieren → Teilen → „An FinSight senden“. Das Ergebnis steht unter Datenimport.' : 'Done: export in Finanzguru → Share → “Send to FinSight”. The result appears under Imports.'}</li>
    </ol>
    <p className="muted small">{de ? 'Tipp: In Safari „Teilen → Zum Home-Bildschirm“ macht FinSight zur App mit eigenem Symbol.' : 'Tip: In Safari “Share → Add to Home Screen” turns FinSight into an app with its own icon.'}</p>
    {!!keys.data?.length && <DataTable headers={[de ? 'Gerät' : 'Device', de ? 'Schlüssel endet auf' : 'Key ends with', de ? 'Erstellt' : 'Created', de ? 'Zuletzt benutzt' : 'Last used', '']}>
      {keys.data.map(k => <tr key={k.id}><td>{k.name}</td><td><code>…{k.hint}</code></td><td className="small">{formatDate(k.created_at.slice(0, 10), language)}</td><td className="small">{k.last_used_at ? formatDate(k.last_used_at.slice(0, 10), language) : '—'}</td>
        <td><Button variant="ghost" aria-label={`${de ? 'Widerrufen' : 'Revoke'}: ${k.name}`} onClick={() => revoke.mutate(k.id)}><Trash2 size={15} /></Button></td></tr>)}
    </DataTable>}
    <Feedback error={create.error || revoke.error} />
  </Panel>
}
