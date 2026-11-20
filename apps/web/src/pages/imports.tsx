import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CloudUpload, FileSpreadsheet, ShieldCheck, X } from 'lucide-react'
import { api, items } from '../lib/api'
import type { Coverage, Import } from '../lib/types'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Feedback, Notice, PageHeader, Panel, QueryState } from '../components/ui'
import { NewAccountsPrompt } from '../components/new-accounts'

type Preview = { row_count?: number; columns?: string[]; warnings?: string[]; preview?: Record<string, unknown>[]; rows?: Record<string, unknown>[]; preview_id?: string }
export default function ImportsPage() {
  const { t, language } = useLocale(); const client = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [full, setFull] = useState(true)
  const input = useRef<HTMLInputElement>(null)
  const query = useQuery({ queryKey: ['imports'], queryFn: async () => items(await api<Import[] | { items: Import[] }>('/imports')).map(i => ({ ...i, imported: i.summary?.added ?? i.imported, updated: i.summary?.changed ?? i.updated, unchanged: i.summary?.unchanged ?? i.unchanged })), refetchInterval: q => items(q.state.data).some(i => ['queued', 'processing', 'pending', 'running'].includes(i.status)) ? 2500 : false })
  const preview = useMutation({ mutationFn: async () => { const body = new FormData(); body.append('file', file!); return api<Preview>('/imports/preview', { method: 'POST', body }) } })
  const upload = useMutation({ mutationFn: async () => { const body = new FormData(); body.append('file', file!); body.append('full_snapshot', String(full)); body.append('background', 'true'); return api('/imports', { method: 'POST', body }) }, onSuccess: () => { setFile(null); preview.reset(); if (input.current) input.current.value = ''; client.invalidateQueries({ queryKey: ['imports'] }); client.invalidateQueries({ queryKey: ['overview'] }); client.invalidateQueries({ queryKey: ['accounts'] }); client.invalidateQueries({ queryKey: ['transactions'] }) } })
  const choose = (chosen?: File) => { if (!chosen || preview.isPending || upload.isPending) return; setFileError(!chosen.name.toLowerCase().endsWith('.xlsx') || chosen.size > 25 * 1024 * 1024 || chosen.size === 0); setFile(chosen.name.toLowerCase().endsWith('.xlsx') && chosen.size <= 25 * 1024 * 1024 && chosen.size > 0 ? chosen : null); preview.reset(); upload.reset(); if (input.current) input.current.value = '' }
  const previewRows = preview.data?.preview || preview.data?.rows || []
  const columns = preview.data?.columns || Object.keys(previewRows[0] || {})
  return <>
    <PageHeader title={t('imports')} description={t('importsIntro')} />
    <Panel>
      <div className={`dropzone ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files[0]) }}>
        <span className="upload-icon"><CloudUpload size={30} /></span><h2>{t('drop')}</h2><p>{t('dropText')}</p>
        <input ref={input} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="sr-only" aria-label={t('choose')} onChange={e => choose(e.target.files?.[0])} disabled={preview.isPending || upload.isPending} />
        <Button variant="outline" onClick={() => input.current?.click()} disabled={preview.isPending || upload.isPending}>{t('choose')}</Button>
      </div>
      <label className="check-row"><input type="checkbox" checked={full} onChange={e => setFull(e.target.checked)} /> <span>{t('importFull')}</span></label>
      <p className="upload-privacy"><ShieldCheck size={15} />{t('importPrivacy')}</p>
      {fileError && <div role="alert" className="feedback error">{t('fileError')}</div>}
      {file && <div className="selected-file"><FileSpreadsheet size={25} /><div><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB</small></div><Button variant="ghost" aria-label={t('cancel')} disabled={preview.isPending || upload.isPending} onClick={() => { setFile(null); preview.reset() }}><X size={17} /></Button><Button onClick={() => preview.mutate()} busy={preview.isPending} disabled={upload.isPending}>{t('preview')}</Button></div>}
      <Feedback error={preview.error || upload.error} success={upload.isSuccess} />
      {preview.data && <div className="preview"><div className="panel-heading"><h2>{t('preview')} <Badge>{preview.data.row_count ?? '—'} {t('rows')}</Badge></h2><Button onClick={() => upload.mutate()} busy={upload.isPending}>{t('upload')}</Button></div>{preview.data.warnings?.map((w, i) => <Notice key={i} warning>{w}</Notice>)}
        <div className="badge-row">{columns.map(c => <Badge key={c}>{c}</Badge>)}</div>
        {!!previewRows.length && <DataTable headers={columns}>{previewRows.slice(0, 10).map((row, i) => <tr key={i}>{columns.map(c => <td key={c}>{typeof row[c] === 'object' ? JSON.stringify(row[c]) : String(row[c] ?? '')}</td>)}</tr>)}</DataTable>}
        <Notice>{t('importWarning')}</Notice>
      </div>}
    </Panel>
    {items(query.data).some(i => i.status === 'processing') && <Notice>{language === 'de' ? 'Ein Import läuft im Hintergrund. Du kannst die Seite verlassen; der Status aktualisiert sich automatisch.' : 'An import is running in the background. You can leave this page; the status updates automatically.'}</Notice>}
    <NewAccountsPrompt />
    <DataQuality />
    <CoverageReport imports={items(query.data)} />
    <Panel title={t('history')} description={t('reconciliation')}>
      <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!items(query.data).length}>
        <DataTable headers={[t('name'), t('date'), t('status'), t('rows'), t('reconciliation')]}>{items(query.data).map(i => <tr key={i.id}><td><div className="file-name"><FileSpreadsheet size={18} />{i.filename || i.id}</div></td><td className="nowrap muted">{formatDate(i.created_at, language)}</td><td><Badge tone={['failed', 'error'].includes(i.status) ? 'warning' : ''}>{i.status}</Badge></td><td>{i.row_count ?? '—'}</td><td className="small muted">{language === 'de' ? 'Neu / Geändert / Unverändert' : 'New / Updated / Unchanged'}: {i.summary?.inserted ?? i.imported ?? '—'} / {i.summary?.updated ?? i.updated ?? '—'} / {i.summary?.unchanged ?? i.unchanged ?? '—'}{['failed', 'error'].includes(i.status) && <p>{language === 'de' ? 'Bitte Datei erneut auswählen und importieren.' : 'Please select the file again to retry the import.'}</p>}</td></tr>)}</DataTable>
      </QueryState>
    </Panel>
  </>
}


type Gaps = { accounts: { id: string; name: string; first_month: string; last_month: string; empty_months: string[]; low_months: string[]; ended_early_months: number; in_window: boolean }[]; affected_accounts: number; window_gap_accounts: number; last_complete_month?: string; window_start_month?: string }
function DataQuality() {
  const { language } = useLocale()
  const de = language === 'de'
  const query = useQuery({ queryKey: ['data-quality'], queryFn: () => api<Gaps>('/data-quality') })
  const data = query.data
  if (!data || !Array.isArray(data.accounts)) return null
  if (!data.accounts.length) return <Panel title={de ? 'Datenqualität' : 'Data quality'}><p className="muted">{de ? 'Keine Lücken in den Buchungen deiner Konten gefunden.' : 'No gaps found in your accounts\' bookings.'}</p></Panel>
  return <Panel title={de ? 'Datenqualität' : 'Data quality'} description={de
    ? `Monate ohne oder mit auffallend wenigen Buchungen und Konten, die früher enden als die übrigen Daten. Das verfälscht Durchschnitte und senkt die Sicherheit der Wunsch-Bewertung. Hervorgehoben: Lücken in den letzten 12 Monaten (ab ${data.window_start_month}). Ein frischer Export oder „inaktiv“ beim Konto löst das.`
    : `Months without or with unusually few bookings, and accounts that end earlier than the rest. Highlighted: gaps within the last 12 months (from ${data.window_start_month}).`}>
    <ul className="gap-list">{data.accounts.map(a => <li key={a.id} className={a.in_window ? 'gap-in-window' : 'muted'}>
      <strong>{a.name}</strong> <Badge tone={a.in_window ? 'warning' : ''}>{a.first_month} – {a.last_month}</Badge>
      {a.empty_months.length > 0 && <div>{de ? 'Keine Buchungen in:' : 'No bookings in:'} {a.empty_months.join(', ')}</div>}
      {a.low_months.length > 0 && <div>{de ? 'Auffallend wenige Buchungen in:' : 'Unusually few bookings in:'} {a.low_months.join(', ')}</div>}
      {a.ended_early_months > 0 && <div>{de ? `Letzte Buchung ${a.ended_early_months} Monate vor dem Ende der übrigen Daten (${data.last_complete_month}).` : `Last booking ${a.ended_early_months} months before the other data ends (${data.last_complete_month}).`}</div>}
    </li>)}</ul>
  </Panel>
}

function CoverageReport({ imports }: { imports: Import[] }) {
  const { language } = useLocale(); const de = language === 'de'
  const latest = imports.find(i => i.status === 'completed' && i.summary?.coverage?.length)
  if (!latest) return null
  const rows: Coverage[] = latest.summary!.coverage!
  const shrunk = latest.summary?.shrunk_accounts ?? []
  return <Panel title={de ? 'Abdeckung je Konto' : 'Coverage per account'} description={latest.filename}>
    {shrunk.length > 0 && <Notice>{de ? `Die Historie ist bei diesen Konten kleiner geworden: ${shrunk.join(', ')}. Die fehlenden Buchungen bleiben erhalten und zählen weiter mit.` : `History shrank for: ${shrunk.join(', ')}. Missing bookings are kept and still count.`}</Notice>}
    <DataTable headers={[de ? 'Konto' : 'Account', de ? 'Zeilen' : 'Rows', de ? 'Erste' : 'First', de ? 'Letzte' : 'Last', de ? 'Vorher' : 'Before', de ? 'Fehlend' : 'Missing']}>
      {rows.map(r => <tr key={r.account}><td>{r.account}{r.shrunk && <> <Badge tone="warning">{de ? 'geschrumpft' : 'shrunk'}</Badge></>}</td><td>{r.rows}</td><td className="nowrap">{r.first}</td><td className="nowrap">{r.last}</td><td>{r.previous_rows}</td><td>{r.missing}</td></tr>)}
    </DataTable>
  </Panel>
}
